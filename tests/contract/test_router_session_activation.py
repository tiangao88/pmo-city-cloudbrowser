"""Router session activation: ``POST /v1/session/activate``.

The authenticated edge's own session must go ``OFFERED -> ACTIVE`` only by
waking its assigned slot under the server-minted binding:

- identity is resolved server-side from edge headers (never ``Remote-Email``);
- a session in ``OFFERED`` with a binding wakes its slot via the supervisor
  client (binding forwarded server-side) and then flips to ``ACTIVE`` with
  a ``session_ttl_s``;
- an already ``ACTIVE`` session re-wakes idempotently and stays ``ACTIVE``;
- ``WAITING`` sessions and sessions without a binding fail with bounded
  error codes and never touch the supervisor;
- supervisor ``slot_mismatch``/failure keeps the session ``OFFERED``;
- responses stay bounded: no principal IDs, emails, or binding values.
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server
from cloudbrowser.identity_links import IdentityLinkClient
from cloudbrowser.router.router_api import RouterApi, create_router_server
from cloudbrowser.router.sessions import RouterSessionStore, SlotDescriptor


_OIDC_ISSUER = "https://auth.example.test"
_TINYAUTH_REALM = "tinyauth.example.test"
_LINK_SECRET = "identity-link-router-secret-0123456789ab"


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _RecordingSupervisor:
    """Records post_control calls; wake returns ready by default."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.known_slots = frozenset({"slot-1", "slot-2"})
        self.fail_with: str | None = None

    def post_control(self, slot_id: str, *, operation: str, request_id: str, binding=None):
        self.calls.append(
            {
                "slot_id": slot_id,
                "operation": operation,
                "request_id": request_id,
                "binding": binding,
            }
        )
        if self.fail_with is not None:
            return {
                "request_id": request_id,
                "status": "failed",
                "error_code": self.fail_with,
            }
        return {
            "request_id": request_id,
            "status": "ready",
            "state": "ready",
            "restored_count": 0,
        }


def _identity_headers(
    *, sub: str | None = "oidc-sub-1", user: str = "local-owner", email: str = "owner@example.com"
) -> dict[str, str]:
    headers = {
        "Remote-User": user,
        "Remote-Email": email,
        "Remote-Groups": "PMOC_Users",
    }
    if sub is not None:
        headers["Remote-OIDC-Issuer"] = _OIDC_ISSUER
        headers["Remote-Sub"] = sub
    else:
        headers["Remote-Tinyauth-Realm"] = _TINYAUTH_REALM
    return headers


@pytest.fixture
def server_stack(tmp_path: Path):
    store = RouterSessionStore(
        tmp_path / "router.json",
        slots=(
            SlotDescriptor("slot-1", "http://supervisor-1:8081", "browser-1"),
            SlotDescriptor("slot-2", "http://supervisor-2:8081", "browser-2"),
        ),
        clock=_Clock(),
    )
    supervisor = _RecordingSupervisor()
    identity_store = IdentityLinkStore(tmp_path / "identity-links.sqlite3", clock=lambda: 1000.0)
    identity_server = create_identity_link_server(
        identity_store,
        shared_secret=_LINK_SECRET,
        oidc_issuer=_OIDC_ISSUER,
        tinyauth_realm=_TINYAUTH_REALM,
        address=("127.0.0.1", 0),
    )
    identity_thread = threading.Thread(target=identity_server.serve_forever, daemon=True)
    identity_thread.start()
    identity_client = IdentityLinkClient(
        base_url=f"http://127.0.0.1:{identity_server.server_address[1]}",
        shared_secret=_LINK_SECRET,
        oidc_issuer=_OIDC_ISSUER,
        tinyauth_realm=_TINYAUTH_REALM,
        timeout_s=2.0,
    )
    api = RouterApi(
        session_store=store,
        supervisor_client=supervisor,  # type: ignore[arg-type]
        identity_client=identity_client,
    )
    server = create_router_server(api, address=("127.0.0.1", 0))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield {
        "server": server,
        "thread": server_thread,
        "store": store,
        "supervisor": supervisor,
    }
    server.shutdown()
    server_thread.join(timeout=3)
    server.server_close()
    identity_server.shutdown()
    identity_thread.join(timeout=3)
    identity_server.server_close()


def _conn(server: ThreadingHTTPServer) -> HTTPConnection:
    return HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)


def _request_json(
    conn: HTTPConnection,
    *,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, object]]:
    merged = dict(headers or {})
    if body is not None and "Content-Type" not in {key.title() for key in merged}:
        merged["Content-Type"] = "application/json"
    conn.request(method, path, body=body, headers=merged)
    response = conn.getresponse()
    raw = response.read()
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    conn.close()
    return response.status, payload


def _open_session(server) -> dict[str, object]:
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": "req-open"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert status == 200
    return payload


def test_activate_wakes_slot_with_server_binding_and_goes_active(server_stack):
    server = server_stack["server"]
    supervisor = server_stack["supervisor"]
    offered = _open_session(server)
    assert offered["status"] == "offered"
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "active"
    assert payload["slot_id"] == offered["slot_id"]
    assert isinstance(payload["session_ttl_s"], float)
    assert len(supervisor.calls) == 1
    call = supervisor.calls[0]
    assert call["operation"] == "wake"
    assert call["slot_id"] == offered["slot_id"]
    binding = call["binding"]
    assert binding is not None and binding.browser_id == "browser-1"
    assert binding.principal_id.startswith("pmo-")
    # Response carries no identity/binding material.
    rendered = json.dumps(payload)
    assert "pmo-" not in rendered
    assert "owner@example.com" not in rendered
    assert "generation-" not in rendered


def test_activate_is_idempotent_for_active_session(server_stack):
    server = server_stack["server"]
    supervisor = server_stack["supervisor"]
    _open_session(server)
    first = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act-1"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert first[1]["status"] == "active"
    second = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act-2"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert second[1]["status"] == "active"
    assert second[0] == 200


def test_activate_without_session_fails_bounded(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "session_not_found"
    assert server_stack["supervisor"].calls == []


def test_activate_missing_identity_unauthorized(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act"}).encode("utf-8"),
    )
    assert status == 401
    assert payload["error_code"] == "unauthorized"


def test_activate_supervisor_failure_keeps_session_offered(server_stack):
    server = server_stack["server"]
    supervisor = server_stack["supervisor"]
    _open_session(server)
    supervisor.fail_with = "slot_mismatch"
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "slot_mismatch"
    status2, payload2 = _request_json(
        _conn(server), method="GET", path="/v1/session", headers=_identity_headers()
    )
    assert status2 == 200
    assert payload2["status"] == "offered"


def test_activate_surfaces_supervisor_error_code(server_stack):
    server = server_stack["server"]
    supervisor = server_stack["supervisor"]
    _open_session(server)
    supervisor.fail_with = "operation_failed"
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session/activate",
        body=json.dumps({"request_id": "req-act"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "operation_failed"
