"""RED tests: agent-control transport expectations rotate with the lease.

``rotate_lease`` (and the trusted ``POST /agent-control/lease`` route) must
rotate not only the service's expected principal/browser/generation but also
the underlying browser transports' ``expected_owner``/``expected_generation``
— otherwise every post-rotation readiness probe fails closed against the
stale boot binding and no forwarded page action can ever succeed.
"""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.agent_browser_http import HttpAgentBrowserTransport
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.agent_control import AgentControlService, PageState, RestrictedAgentBrowser


_SECRET = "router-agent-shared-secret-0123456789"


class _FakeAgentClient:
    """Captures requests; /agent/readiness reports the live binding."""

    def __init__(self, state: dict[str, object]) -> None:
        self._state = state
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, body: object | None = None, headers: dict[str, str] | None = None) -> object:
        self.calls.append((method, path))
        if path == "/agent/readiness":
            return {
                "owner": self._state["owner"],
                "generation": self._state["generation"],
                "cdp_ok": self._state["cdp_ok"],
            }
        return {"ok": True}


def test_http_browser_transport_exposes_binding_rotation() -> None:
    client = _FakeAgentClient({})
    transport = HttpBrowserTransport(
        client,  # type: ignore[arg-type]
        expected_owner="principal-unassigned",
        expected_generation="generation-0",
    )
    transport.rotate_binding("pmo-owner", "generation-q-1")
    assert transport.expected_owner == "pmo-owner"
    assert transport.expected_generation == "generation-q-1"


def test_http_agent_transport_exposes_binding_rotation() -> None:
    client = _FakeAgentClient({})
    transport = HttpAgentBrowserTransport(
        client,  # type: ignore[arg-type]
        expected_owner="principal-unassigned",
        expected_generation="generation-0",
    )
    transport.rotate_binding("pmo-owner", "generation-q-1")
    assert transport.expected_owner == "pmo-owner"
    assert transport.expected_generation == "generation-q-1"


def test_lease_rotation_updates_underlying_transports() -> None:
    """After a trusted lease rotation the transports must expect the new
    binding so a browser that actually holds it passes readiness."""
    state = {
        "owner": "pmo-owner",
        "generation": "generation-q-abc123",
        "cdp_ok": True,
    }
    server = AgentControlService.create_server(
        RestrictedAgentBrowser(
            readiness=lambda: _readiness(state),
            page_info=lambda target_tab_id, selector=None: PageState(url="https://example.test", title="Example", text="Hello"),
        ),
        principal_id="principal-unassigned",
        browser_id="browser-slot-1",
        generation="generation-0",
        shared_secret=_SECRET,
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _post(
            server,
            "/agent-control/lease",
            headers={"X-CB-Trusted-Secret": _SECRET},
            body={
                "binding": {
                    "principal_id": "pmo-owner",
                    "profile_id": "profile-pmo-owner",
                    "browser_id": "browser-slot-1",
                    "generation": "generation-q-abc123",
                }
            },
        )
        assert response.status == 200
        # Page action with the new binding envelope succeeds because the
        # transports were rotated together with the lease.
        action = _post(
            server,
            "/agent-control/v1",
            headers={
                "X-CB-Trusted-Secret": _SECRET,
                "X-CB-Principal": "pmo-owner",
                "X-CB-Browser": "browser-slot-1",
                "X-CB-Generation": "generation-q-abc123",
            },
            body={"request_id": "r1", "operation": "page_info", "params": {"target_tab_id": "tab-1"}},
        )
        payload = json.loads(action.read())
        assert payload["status"] == "ok", payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _readiness(state: dict[str, object]):
    from cloudbrowser.browser_slots import BrowserReadiness

    return BrowserReadiness(
        state["owner"],  # type: ignore[arg-type]
        state["generation"],  # type: ignore[arg-type]
        state["cdp_ok"],  # type: ignore[bool]
    )


def _post(server, path: str, *, headers: dict[str, str], body: dict[str, object]):
    data = json.dumps(body).encode()
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=data,
        method="POST",
        headers=headers,
    )
    return urlopen(request, timeout=2)
