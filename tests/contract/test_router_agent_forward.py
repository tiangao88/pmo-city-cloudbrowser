"""RED tests: router control-api/v1 surface — POST /v1/agent/<operation> (§3.1).

The authenticated edge sends a page-action intent; the router derives the
binding, slot, browser, and generation exclusively from server-side session
state and relays the request to the assigned slot's agent-control service via
the trusted forwarder. Caller-supplied fields can never choose the slot,
binding, or identity.

Decision matrix tested here:

- unresolvable identity                → 401 unauthorized
- no session (or waiting/unbound)      → session_not_found
- ACTIVE session without a binding     → no_binding
- operation outside the allowlist      → capability_denied (forbidden) /
                                          operation_not_supported (unknown)
- assigned slot not in forwarder map   → unknown_slot
- happy path                           → bounded relay of {status, page?}
- responses never contain principal,
  binding, email, or secret values
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.browser_slots import BrowserBinding
from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server
from cloudbrowser.identity_links import IdentityLinkClient
from cloudbrowser.router.router_api import RouterApi, create_router_server
from cloudbrowser.router.sessions import RouterSessionStore, SlotDescriptor, SessionStatus


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


class _RecordingForwarder:
    """Minimal in-process stand-in for ``AgentControlForwarder``."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.known_slots = frozenset({"slot-1", "slot-2"})
        self.result: dict[str, object] = {
            "request_id": "req-agent",
            "status": "ok",
            "page": {"url": "https://example.test", "title": "Example", "text": "Hello"},
        }

    def forward(self, slot_id: str, *, binding: BrowserBinding, operation: str, params: dict[str, object], request_id: str) -> dict[str, object]:
        self.calls.append(
            {
                "slot_id": slot_id,
                "binding": binding,
                "operation": operation,
                "params": dict(params),
                "request_id": request_id,
            }
        )
        return dict(self.result, request_id=request_id)


class _IdentityOnlyForwarder(_RecordingForwarder):
    known_slots = frozenset({"slot-other"})  # type: ignore[assignment]


@pytest.fixture
def stack(tmp_path: Path):
    store = RouterSessionStore(
        tmp_path / "router.json",
        slots=(
            SlotDescriptor("slot-1", "http://supervisor-1:8081", "browser-1"),
            SlotDescriptor("slot-2", "http://supervisor-2:8081", "browser-2"),
        ),
        clock=_Clock(),
    )
    forwarder = _RecordingForwarder()
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
        supervisor_client=_NullSupervisor(),  # type: ignore[arg-type]
        identity_client=identity_client,
        agent_control_forwarder=forwarder,  # type: ignore[arg-type]
    )
    server = create_router_server(api, address=("127.0.0.1", 0))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield {
        "server": server,
        "store": store,
        "forwarder": forwarder,
        "identity_store": identity_store,
    }
    server.shutdown()
    server_thread.join(timeout=3)
    server.server_close()
    identity_server.shutdown()
    identity_thread.join(timeout=3)


class _NullSupervisor:
    known_slots = frozenset({"slot-1", "slot-2"})

    def post_control(self, slot_id: str, *, operation: str, request_id: str) -> dict[str, object]:
        raise AssertionError("slot lifecycle must not be touched by agent routes")


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


def _principal_for(stack: dict, *, sub: str) -> str:
    """Resolve the server-minted principal via the fixture's identity store."""
    from cloudbrowser.identity_links import IdentityLinkKey

    principal = stack["identity_store"].resolve(
        IdentityLinkKey("oidc", _OIDC_ISSUER, sub), groups=("PMOC_Users",)
    )
    assert principal is not None and principal.startswith("pmo-")
    return principal


def _open_active_session(stack: dict) -> dict[str, object]:
    """Enqueue + activate a session for the test principal; return record."""
    conn = _conn(stack["server"])
    _request_json(
        conn,
        method="POST",
        path="/v1/session",
        body=json.dumps({"request_id": "req-open"}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    session = stack["store"].for_principal(_principal_for(stack, sub="oidc-sub-1"))
    assert session is not None and session.slot_id is not None
    activated = stack["store"].activate(session.session_id)
    assert activated.status is SessionStatus.ACTIVE
    return {
        "session_id": activated.session_id,
        "slot_id": activated.slot_id,
        "binding": activated.binding,
    }


def test_agent_route_relays_page_info_to_session_slot(stack) -> None:
    active = _open_active_session(stack)
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-agent", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["status"] == "ok"
    assert payload["page"]["url"] == "https://example.test"
    call = stack["forwarder"].calls[0]
    assert call["slot_id"] == active["slot_id"]
    assert call["binding"] == active["binding"]
    assert call["operation"] == "page_info"
    assert call["request_id"] == "req-agent"


def test_agent_route_requires_resolvable_identity(stack) -> None:
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        # Email-only identity is non-authoritative by design → unresolvable.
        headers={"Remote-Email": "nobody@example.com"},
    )
    conn.close()
    assert status == 401
    assert payload["error_code"] == "unauthorized"
    assert stack["forwarder"].calls == []


@pytest.mark.parametrize(
    "setup",
    [None, "waiting"],
)
def test_agent_route_without_session_or_unbound_fails_closed(stack, setup) -> None:
    if setup == "waiting":
        # Force the caller's session into WAITING by enqueueing two principals
        # so the second has no slot assignment.
        first = _conn(stack["server"])
        _request_json(
            first,
            method="POST",
            path="/v1/session",
            body=json.dumps({"request_id": "req-first"}).encode("utf-8"),
            headers=_identity_headers(sub="oidc-sub-first", user="first-owner", email="first@example.com"),
        )
        first.close()
        second = _conn(stack["server"])
        _request_json(
            second,
            method="POST",
            path="/v1/session",
            body=json.dumps({"request_id": "req-second"}).encode("utf-8"),
            headers=_identity_headers(sub="oidc-sub-1", user="second-owner", email="second@example.com"),
        )
        second.close()
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["status"] == "failed"
    assert payload["error_code"] == "session_not_found"
    assert stack["forwarder"].calls == []


def test_agent_route_with_active_session_without_binding_fails_no_binding(stack) -> None:
    _open_active_session(stack)
    # Strip the binding to simulate a store that lost the lease fields.
    session = stack["store"].for_principal(_principal_for(stack, sub="oidc-sub-1"))
    assert session is not None
    import dataclasses

    stripped = dataclasses.replace(session, binding=None)
    stack["store"]._sessions[session.session_id] = stripped  # type: ignore[attr-defined]
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["error_code"] == "no_binding"
    assert stack["forwarder"].calls == []


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/v1/agent/raw_cdp", "capability_denied"),
        ("/v1/agent/evaluate", "capability_denied"),
        ("/v1/agent/cookies", "capability_denied"),
        ("/v1/agent/storage", "capability_denied"),
        ("/v1/agent/exec", "operation_not_supported"),
    ],
)
def test_agent_route_forbidden_or_unknown_operations_are_denied_before_forward(stack, path: str, expected: str) -> None:
    _open_active_session(stack)
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path=path,
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["error_code"] == expected
    assert stack["forwarder"].calls == []


def test_agent_route_unknown_slot_fails_without_forwarding(stack) -> None:
    _open_active_session(stack)
    # Rebind the session to a slot the forwarder does not know about.
    session = stack["store"].for_principal(_principal_for(stack, sub="oidc-sub-1"))
    assert session is not None
    import dataclasses

    rebound = dataclasses.replace(session, slot_id="slot-x")
    stack["store"]._sessions[session.session_id] = rebound  # type: ignore[attr-defined]
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["error_code"] == "unknown_slot"
    assert stack["forwarder"].calls == []


def test_agent_route_forwards_only_for_callers_own_session(stack) -> None:
    """A second principal with an ACTIVE session cannot drive another
    principal's slot: forwarding is keyed on the caller's own session only."""
    _open_active_session(stack)
    # A different principal with no session must get session_not_found even
    # though slot-1 is occupied by an active session.
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(sub="oidc-sub-other", user="other-owner", email="other@example.com"),
    )
    conn.close()
    assert status == 200
    assert payload["error_code"] == "session_not_found"
    assert stack["forwarder"].calls == []


def test_agent_route_responses_never_leak_identity_or_binding(stack) -> None:
    _open_active_session(stack)
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    text = json.dumps(payload)
    assert "pmo-owner" not in text
    assert "owner@example.com" not in text
    assert "oidc-sub-1" not in text
    assert "profile-pmo-owner" not in text
    assert "generation-" not in text


def test_agent_route_malformed_body_is_invalid_request(stack) -> None:
    _open_active_session(stack)
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"params": {}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["error_code"] == "invalid_request"
    assert stack["forwarder"].calls == []


def test_agent_route_maps_forwarder_unavailability_to_bounded_error(stack) -> None:
    _open_active_session(stack)
    stack["forwarder"].result = {}  # forwarder returns unusable payload
    from cloudbrowser.router.agent_control_forwarder import AgentControlUnavailable

    def _boom(*args: object, **kwargs: object) -> dict[str, object]:
        raise AgentControlUnavailable("agent control is unreachable")

    stack["forwarder"].forward = _boom  # type: ignore[method-assign]
    conn = _conn(stack["server"])
    status, payload = _request_json(
        conn,
        method="POST",
        path="/v1/agent/page_info",
        body=json.dumps({"request_id": "req-1", "params": {"target_tab_id": "tab-1"}}).encode("utf-8"),
        headers=_identity_headers(),
    )
    conn.close()
    assert status == 200
    assert payload["error_code"] == "agent_unavailable"
    assert "unreachable" not in json.dumps(payload)
