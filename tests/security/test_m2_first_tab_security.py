"""The first-tab capability cannot become a raw navigation escape hatch."""
import pytest

from cloudbrowser.agent_control import AgentControlRequest, AgentControlService, RestrictedAgentBrowser
from cloudbrowser.browser_slots import BrowserReadiness


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "data:text/html,secret", "javascript:alert(1)",
    "https://user:password@example.test/", "https://example.test/#fragment",
])
def test_tab_open_rejects_non_public_or_credential_bearing_urls(url):
    calls = []
    service = AgentControlService(
        RestrictedAgentBrowser(
            readiness=lambda: BrowserReadiness("alice", "g1", True),
            open_tab=lambda value: calls.append(value),
        ),
        principal_id="alice", browser_id="slot-1", generation="g1",
    )
    result = service.handle(AgentControlRequest(
        request_id="req-bad", principal_id="alice", browser_id="slot-1",
        generation="g1", operation="tab_open", params={"url": url},
    ))
    assert result == {"request_id": "req-bad", "status": "failed", "error_code": "invalid_request"}
    assert calls == []


def test_tab_open_still_requires_current_owner_binding():
    calls = []
    service = AgentControlService(
        RestrictedAgentBrowser(
            readiness=lambda: BrowserReadiness("alice", "g1", True),
            open_tab=lambda value: calls.append(value),
        ),
        principal_id="alice", browser_id="slot-1", generation="g1",
    )
    result = service.handle(AgentControlRequest(
        request_id="req-bob", principal_id="bob", browser_id="slot-1",
        generation="g1", operation="tab_open", params={"url": "https://example.test/"},
    ))
    assert result["error_code"] == "owner_mismatch"
    assert calls == []


def test_tab_open_rejects_unexpected_parameters():
    calls = []
    service = AgentControlService(
        RestrictedAgentBrowser(
            readiness=lambda: BrowserReadiness("alice", "g1", True),
            open_tab=lambda value: calls.append(value),
        ), principal_id="alice", browser_id="slot-1", generation="g1",
    )
    result = service.handle(AgentControlRequest(
        request_id="req-extra", principal_id="alice", browser_id="slot-1",
        generation="g1", operation="tab_open",
        params={"url": "https://example.test/", "raw_cdp": True},
    ))
    assert result["error_code"] == "invalid_request"
    assert calls == []
