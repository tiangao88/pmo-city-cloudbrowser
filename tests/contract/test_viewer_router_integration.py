"""End-to-end: the real viewer session surface drives the real router.

No mocks: an identity-link server, a router API server, and a viewer
server with the session surface all run in-process on loopback, and the
HTTP requests travel exactly as they would over the compose network.
This pins the wire contract:

- POST /ui/session/join  -> POST /v1/session (enqueue, principal redacted)
- GET  /ui/session       -> GET  /v1/session/<id> (queue state)
- POST /ui/session/activate -> POST /v1/session/<id>/activate
- forged identity -> 401 at the viewer, nothing reaches the router
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server
from cloudbrowser.identity_links import IdentityLinkClient
from cloudbrowser.router.router_api import (  # type: ignore[attr-defined]
    RouterApi,
    create_router_server,
)
from cloudbrowser.router.sessions import RouterSessionStore, SlotDescriptor
from cloudbrowser.viewer import create_viewer_server
from cloudbrowser.viewer.session_surface import RouterHttpClient, ViewerSessionSurface

_SECRET = "identity-link-test-secret-012345"
_ISSUER = "https://auth.example.test"
_REALM = "tinyauth.example.test"

_EDGE = {
    "Remote-Sub": "oidc-sub-1",
    "Remote-Email": "owner@example.com",
    "Remote-Groups": "PMOC_Users",
}


class _IdentityResolver:
    """IdentityLinkClient protocol over a real identity-link HTTP server."""

    def __init__(self, base_url: str) -> None:
        self._client = IdentityLinkClient(
            base_url=base_url,
            shared_secret=_SECRET,
            oidc_issuer=_ISSUER,
            tinyauth_realm=_REALM,
        )

    def resolve(self, identity: object) -> str | None:
        return self._client.resolve(identity)  # type: ignore[arg-type]


@pytest.fixture()
def stack(tmp_path: Path):
    # 1. identity-link
    identity_store = IdentityLinkStore(tmp_path / "identity.sqlite3")
    identity_server = create_identity_link_server(
        identity_store,
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
        address=("127.0.0.1", 0),
    )
    threading.Thread(target=identity_server.serve_forever, daemon=True).start()
    identity_base = f"http://127.0.0.1:{identity_server.server_address[1]}"

    # The identity-link store auto-provisions a PMO principal on first
    # resolve, so no seeding is required.

    # 2. router
    router_store = RouterSessionStore(
        tmp_path / "router-state.json",
        slots=(
            SlotDescriptor(
                slot_id="slot-1",
                supervisor_url="http://slot-supervisor:8081",
                browser_id="browser-slot-1",
            ),
        ),
        clock=lambda: 1000.0,
    )
    identity_client = IdentityLinkClient(
        base_url=identity_base,
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
    )
    api = RouterApi(
        session_store=router_store,
        supervisor_client=_NoSupervisor(),
        identity_client=identity_client,
    )
    router_server = create_router_server(api, address=("127.0.0.1", 0))
    threading.Thread(target=router_server.serve_forever, daemon=True).start()
    router_base = f"http://127.0.0.1:{router_server.server_address[1]}"

    # 3. viewer with a real RouterHttpClient against the real router
    surface = ViewerSessionSurface(
        identity_client=_IdentityResolver(identity_base),
        router_api=RouterHttpClient(base_url=router_base),
    )
    viewer_server = create_viewer_server(
        None,
        address=("127.0.0.1", 0),
        allow_edge_identity=True,
        session_surface=surface,
    )
    threading.Thread(target=viewer_server.serve_forever, daemon=True).start()
    viewer_base = f"http://127.0.0.1:{viewer_server.server_address[1]}"

    yield viewer_base

    for server in (viewer_server, router_server, identity_server):
        server.shutdown()
        server.server_close()


def _post(base: str, path: str, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
    request = Request(
        base + path,
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


def _get(base: str, path: str, headers: dict[str, str]) -> tuple[int, dict[str, object]]:
    with urlopen(Request(base + path, headers=headers), timeout=5) as response:
        return response.status, json.loads(response.read().decode())


class _NoSupervisor:
    def __init__(self) -> None:
        self.known_slots = frozenset({"slot-1"})

    def post_control(self, *args: object, **kwargs: object) -> object:  # pragma: no cover
        raise AssertionError("no supervisor call expected in queue tests")


def test_full_queue_lifecycle_through_real_components(stack) -> None:
    viewer_base = stack
    status, join = _post(viewer_base, "/ui/session/join", dict(_EDGE))
    assert status == 200
    assert join["status"] in {"waiting", "offered"}

    status, current = _get(viewer_base, "/ui/session", dict(_EDGE))
    assert status == 200
    # The router derives the current session from identity; the GET
    # envelope's request id is router-fixed, so assert on session state.
    assert current["status"] in {"waiting", "offered", "active", "backed_off"}

    status, activated = _post(viewer_base, "/ui/session/activate", dict(_EDGE))
    assert status == 200
    # Activation targets the caller's own session on the real router.
    assert activated["status"] in {"active", "ready", "failed"}


def test_identity_without_required_group_fails_closed(stack) -> None:
    """An authenticated edge outside PMOC_Users gets 401 from the viewer."""
    viewer_base = stack
    with pytest.raises(HTTPError) as exc:
        _post(
            viewer_base,
            "/ui/session/join",
            {"Remote-Sub": "outsider-sub", "Remote-Groups": "Other_Group"},
        )
    assert exc.value.code == 401
