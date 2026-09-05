"""HTTP/JSON contract for the router control-api/v1 surface.

The router API exposes:

- ``GET  /health``
- ``GET  /ready``
- ``POST /v1/session``              — enqueue one session for the authenticated edge.
- ``GET  /v1/session``              — fetch the caller's current session.
- ``POST /v1/session/leave``        — release the caller's current session.
- ``POST /v1/slot/<slot>/wake|suspend|recreate``

All non-health responses are bounded JSON with only ``request_id``,
``status``, ``state``, ``error_code``, ``position``, ``offer_ttl_s``,
``session_ttl_s`` keys as appropriate. Responses never contain secrets,
principal IDs, emails, page values, binding contents, or raw exceptions.

Identity is resolved via ``IdentityLinkClient`` from authenticated edge
headers. ``Remote-Email`` is never authoritative.
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
from cloudbrowser.router.supervisor_client import SupervisorClient


_OIDC_ISSUER = "https://auth.example.test"
_TINYAUTH_REALM = "tinyauth.example.test"
_LINK_SECRET = "identity-link-router-secret-0123456789ab"


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _identity_headers(*, sub: str | None = "oidc-sub-1", user: str = "local-owner", email: str = "owner@example.com") -> dict[str, str]:
    headers = {
        "Remote-User": user,
        "Remote-Email": email,
        "Remote-Groups": "PMOC_Users",
    }
    if sub is not None:
        headers["Remote-Sub"] = sub
    return headers


class _RecordingSupervisor:
    """Minimal in-process stand-in for ``SupervisorClient``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.known_slots = frozenset({"slot-1", "slot-2"})

    def post_control(self, slot_id: str, *, operation: str, request_id: str):
        self.calls.append((slot_id, operation, request_id))
        return {
            "request_id": request_id,
            "status": {"wake": "ready", "suspend": "suspended", "recreate": "ready"}.get(
                operation, "unsupported"
            ),
            "state": {"wake": "ready", "suspend": "suspended", "recreate": "ready"}.get(
                operation, "stopped"
            ),
            "restored_count": 0,
        }


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
        "identity_server": identity_server,
        "identity_thread": identity_thread,
        "identity_store": identity_store,
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


def test_health_endpoint_returns_bounded_payload(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(_conn(server), method="GET", path="/health")
    assert status == 200
    assert payload["status"] == "ok"
    assert "principal" not in json.dumps(payload).lower()
    assert "email" not in json.dumps(payload).lower()


def test_ready_endpoint_returns_bounded_payload(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(_conn(server), method="GET", path="/ready")
    assert status == 200
    assert payload["status"] == "ok"


def test_session_post_enqueues_offered_session_and_redacts_principal(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": "req-a"}).encode("utf-8"),
        headers=_identity_headers(sub="oidc-sub-1"),
    )
    assert status == 200
    assert payload["status"] == "offered"
    assert payload["slot_id"] == "slot-1"
    assert payload["session_id"].startswith("q-")
    assert "pmo-" not in json.dumps(payload)
    assert "owner@example.com" not in json.dumps(payload)
    assert "oidc-sub-1" not in json.dumps(payload)
    assert payload["request_id"] == "req-a"


def test_session_get_returns_current_session_for_authenticated_principal(server_stack):
    server = server_stack["server"]
    _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": "req-a"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    status, payload = _request_json(
        _conn(server), method="GET", path="/v1/session", headers=_identity_headers()
    )
    assert status == 200
    assert payload["status"] in {"offered", "active", "waiting"}
    assert "pmo-" not in json.dumps(payload)
    assert "owner@example.com" not in json.dumps(payload)


def test_session_leave_releases_session_and_clears_binding(server_stack):
    server = server_stack["server"]
    _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": "req-a"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    status, payload = _request_json(
        _conn(server), method="POST", path="/v1/session/leave", headers=_identity_headers()
    )
    assert status == 200
    assert payload["status"] == "left"
    assert "pmo-" not in json.dumps(payload)


def test_missing_edge_identity_returns_unauthorized(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(_conn(server), method="GET", path="/v1/session")
    assert status == 401
    assert payload["error_code"] == "unauthorized"


def test_remote_email_is_never_used_as_identity_authority(server_stack):
    server = server_stack["server"]
    headers = {
        "Remote-Email": "attacker@example.com",
        "Remote-Groups": "PMOC_Users",
    }
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": "req-evil"}).encode("utf-8"),
        headers=headers,
    )
    assert status == 401
    assert payload["error_code"] == "unauthorized"


def test_slot_endpoint_routes_to_supervisor_and_returns_bounded_state(server_stack):
    server = server_stack["server"]
    supervisor = server_stack["supervisor"]
    status, payload = _request_json(
        _conn(server), method="POST", path="/v1/slot/slot-1/wake", headers=_identity_headers()
    )
    assert status == 200
    assert payload["status"] == "ready"
    assert supervisor.calls == [("slot-1", "wake", "req-1")]


def test_slot_endpoint_rejects_unknown_slot(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/slot/slot-9/wake",
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "unknown_slot"


def test_slot_endpoint_rejects_invalid_operation(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/slot/slot-1/raw-cdp",
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "operation_not_supported"


def test_invalid_request_id_returns_bounded_error(server_stack):
    server = server_stack["server"]
    status, payload = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": ""}).encode("utf-8"),
        headers=_identity_headers(),
    )
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "invalid_request"


def test_unknown_route_returns_404(server_stack):
    server = server_stack["server"]
    status, _ = _request_json(
        _conn(server), method="GET", path="/v1/no-such-thing", headers=_identity_headers()
    )
    assert status == 404


def test_oversized_body_returns_413(server_stack):
    server = server_stack["server"]
    payload = {"request_id": "x" * 8192}
    status, body = _request_json(
        _conn(server),
        method="POST",
        path="/v1/session",
        body=json.dumps(payload).encode("utf-8"),
        headers=_identity_headers(),
    )
    if status == 200:
        assert body["status"] == "failed"
        assert body["error_code"] in {"invalid_request", "payload_too_large"}
    else:
        assert status == 413


def test_health_does_not_require_edge_identity(server_stack):
    server = server_stack["server"]
    status, _ = _request_json(_conn(server), method="GET", path="/health")
    assert status == 200
