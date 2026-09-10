"""RED tests: agent-control trusted lease rotation (§3.1).

The deployed router mints per-session bindings (``generation-{session_id}``);
the statically pinned ``CB_BINDING_GENERATION`` can therefore never authorize
a forwarded page action. This slice adds ``POST /agent-control/lease``: a
trusted-secret-gated endpoint that rotates the service's expected binding to
the server-derived lease, gated by the same ``X-CB-Trusted-Secret`` boundary
as every other agent-control route.

Contract tested here:

- Lease rotation requires the exact trusted secret; anything else → 401.
- Lease payloads accept only the allowlisted ``BrowserBinding`` fields
  (principal/browser/generation), bounded, printable.
- After rotation, ``POST /agent-control/v1`` with the new ``X-CB-*`` binding
  headers succeeds; stale-generation envelopes are rejected (401).
- Every page action still requires the underlying browser readiness to match
  the request binding (owner + generation equality, ``cdp_ok`` true);
  a mismatch is ``owner_mismatch`` — the lease never substitutes for the
  browser actually holding the binding.
- Forbidden operations stay denied regardless of the lease.
"""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.agent_control import AgentControlService, PageState, RestrictedAgentBrowser
from cloudbrowser.browser_slots import BrowserReadiness


_SECRET = "router-agent-shared-secret-0123456789"
_LEASE = {
    "principal_id": "pmo-owner",
    "profile_id": "profile-pmo-owner",
    "browser_id": "browser-1",
    "generation": "generation-q-abc123",
}
_BINDING = {
    "X-CB-Principal": "pmo-owner",
    "X-CB-Browser": "browser-1",
    "X-CB-Generation": "generation-q-abc123",
}


class _Browser:
    """Readiness follows the current bound generation; calls are recorded."""

    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    def readiness(self) -> BrowserReadiness:
        return BrowserReadiness(
            str(self.state["owner"]),
            str(self.state["generation"]),
            bool(self.state["cdp_ok"]),
        )

    def page_info(self, target_tab_id: str, selector: str | None = None) -> PageState:
        assert self.state["calls"] is not None
        self.state["calls"].append(("page_info", selector))
        return PageState("https://example.test", "Example", "Hello")

    def navigate(self, target_tab_id: str, url: str) -> None:
        self.state["calls"].append(("navigate", target_tab_id, url))


def _server(state: dict[str, object]):
    browser = RestrictedAgentBrowser(
        readiness=lambda: _Browser(state).readiness(),
        page_info=lambda target_tab_id, selector=None: _Browser(state).page_info(target_tab_id, selector),
    )
    return AgentControlService.create_server(
        browser,
        principal_id="pmo-owner",
        browser_id="browser-1",
        generation="generation-stale",  # static pin; stale by design
        shared_secret=_SECRET,
        address=("127.0.0.1", 0),
    )


def _post(server, path: str, *, headers: dict[str, str], body: dict[str, object] | None):
    all_headers = dict(headers)
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=data,
        method="POST",
        headers=all_headers,
    )
    return urlopen(request, timeout=2)


def _lease_headers(secret: str | None = _SECRET) -> dict[str, str]:
    headers = {}
    if secret is not None:
        headers["X-CB-Trusted-Secret"] = secret
    return headers


def _rotate_lease(server, *, secret: str | None = _SECRET, lease: dict[str, object] | None = None):
    return _post(
        server,
        "/agent-control/lease",
        headers=_lease_headers(secret),
        body={"binding": dict(lease or _LEASE)},
    )


def test_lease_rotation_accepts_trusted_binding_and_enables_page_action() -> None:
    state = {"owner": "pmo-owner", "generation": "generation-q-abc123", "cdp_ok": True, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _rotate_lease(server)
        assert response.status == 200
        assert json.loads(response.read())["status"] == "ok"
        # Forwarded page action with the new binding envelope now succeeds.
        action = _post(server, "/agent-control/v1", headers={"X-CB-Trusted-Secret": _SECRET, **_BINDING}, body={"request_id": "r1", "operation": "page_info", "params": {"target_tab_id": "tab-1"}})
        assert json.loads(action.read())["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "secret",
    [None, "wrong-secret-value-0123456", ""],
)
def test_lease_rotation_requires_the_exact_trusted_secret(secret) -> None:
    state = {"owner": "pmo-owner", "generation": "generation-q-abc123", "cdp_ok": True, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as denied:
            _rotate_lease(server, secret=secret)
        assert denied.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "binding",
    [
        {"principal_id": "pmo-owner", "browser_id": "browser-1", "generation": "generation-q-abc123"},
        {"principal_id": "pmo-owner", "profile_id": "profile-pmo-owner", "browser_id": "browser-1", "generation": "generation-q-abc123", "extra": "x"},
        {"principal_id": "", "profile_id": "profile-pmo-owner", "browser_id": "browser-1", "generation": "generation-q-abc123"},
        {"principal_id": "pmo-owner", "profile_id": "profile-pmo-owner", "browser_id": "browser-1", "generation": "generation\ninject"},
    ],
)
def test_lease_rotation_rejects_malformed_or_injected_bindings(binding) -> None:
    state = {"owner": "pmo-owner", "generation": "generation-q-abc123", "cdp_ok": True, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as denied:
            _post(server, "/agent-control/lease", headers=_lease_headers(_SECRET), body={"binding": binding})
        assert denied.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_stale_generation_envelope_is_rejected_after_lease_rotation() -> None:
    state = {"owner": "pmo-owner", "generation": "generation-q-abc123", "cdp_ok": True, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _rotate_lease(server)
        stale = dict(_BINDING, **{"X-CB-Generation": "generation-old"})
        with pytest.raises(HTTPError) as denied:
            _post(server, "/agent-control/v1", headers={"X-CB-Trusted-Secret": _SECRET, **stale}, body={"request_id": "r1", "operation": "page_info", "params": {"target_tab_id": "tab-1"}})
        assert denied.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lease_never_substitutes_for_browser_holding_the_binding() -> None:
    """Readiness reports the browser still on the OLD generation even after
    the lease rotated → every page action fails closed with owner_mismatch."""
    state = {"owner": "pmo-owner", "generation": "generation-old", "cdp_ok": True, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _rotate_lease(server)
        action = _post(server, "/agent-control/v1", headers={"X-CB-Trusted-Secret": _SECRET, **_BINDING}, body={"request_id": "r1", "operation": "page_info", "params": {"target_tab_id": "tab-1"}})
        payload = json.loads(action.read())
        assert payload["status"] == "failed"
        assert payload["error_code"] == "owner_mismatch"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unready_browser_fails_closed_even_with_valid_lease() -> None:
    state = {"owner": "pmo-owner", "generation": "generation-q-abc123", "cdp_ok": False, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _rotate_lease(server)
        action = _post(server, "/agent-control/v1", headers={"X-CB-Trusted-Secret": _SECRET, **_BINDING}, body={"request_id": "r1", "operation": "page_info", "params": {"target_tab_id": "tab-1"}})
        payload = json.loads(action.read())
        assert payload["status"] == "failed"
        assert payload["error_code"] == "browser_unavailable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_forbidden_operations_remain_denied_after_lease_rotation() -> None:
    state = {"owner": "pmo-owner", "generation": "generation-q-abc123", "cdp_ok": True, "calls": []}
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _rotate_lease(server)
        action = _post(server, "/agent-control/v1", headers={"X-CB-Trusted-Secret": _SECRET, **_BINDING}, body={"request_id": "r1", "operation": "raw_cdp", "params": {"target_tab_id": "tab-1"}})
        payload = json.loads(action.read())
        assert payload["status"] == "unsupported"
        assert payload["error_code"] == "capability_denied"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
