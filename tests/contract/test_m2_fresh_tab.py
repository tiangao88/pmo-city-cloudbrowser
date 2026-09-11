"""First-tab contracts for a fresh owner browser."""
import json

from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport
from cloudbrowser.agent_control import AgentControlRequest, AgentControlService, RestrictedAgentBrowser
from cloudbrowser.browser_slots import BrowserReadiness
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter


def test_owner_bound_agent_can_open_first_exact_tab():
    calls = []
    browser = RestrictedAgentBrowser(
        readiness=lambda: BrowserReadiness("alice", "g1", True),
        open_tab=lambda url: calls.append(url) or {
            "tab_id": "ABC123", "url": url, "title": "untitled",
        },
    )
    response = AgentControlService(
        browser, principal_id="alice", browser_id="slot-1", generation="g1"
    ).handle(AgentControlRequest(
        request_id="req-open", principal_id="alice", browser_id="slot-1",
        generation="g1", operation="tab_open",
        params={"url": "https://example.test/start"},
    ))
    assert response == {
        "request_id": "req-open", "status": "ok",
        "page": {"tab_id": "ABC123", "url": "https://example.test/start", "title": "untitled"},
    }
    assert calls == ["https://example.test/start"]


def test_http_agent_open_tab_returns_exact_target():
    class Client:
        def __init__(self): self.calls = []
        def request(self, method, path, *, body=None, headers=None):
            self.calls.append((method, path, body, headers))
            return {"page": {"tab_id": "ABC123", "url": "https://example.test/start", "title": "untitled"}}

    client = Client()
    browser = HttpAgentBrowser(HttpAgentBrowserTransport(
        client, expected_owner="alice", expected_generation="g1"
    ))
    assert browser.open_tab("https://example.test/start")["tab_id"] == "ABC123"
    assert client.calls == [("POST", "/agent/pages/open", json.dumps(
        {"url": "https://example.test/start"}, separators=(",", ":")
    ), {"X-CB-Principal": "alice", "X-CB-Generation": "g1"})]


def test_chrome_open_page_returns_chrome_target_and_enforces_tab_limit():
    class Chrome:
        def __init__(self, count=0): self.count, self.calls = count, []
        def json_request(self, path, *, method="GET"):
            self.calls.append((method, path))
            if path == "/json/list":
                return [{"type": "page", "id": f"T{i}", "url": "https://existing.test", "title": "Existing"} for i in range(self.count)]
            return {"type": "page", "id": "ABC123", "url": "https://example.test/start", "title": ""}

    chrome = Chrome()
    adapter = ChromeBrowserAdapter(chrome, "alice", "g1")
    assert adapter.open_page("https://example.test/start") == {
        "tab_id": "ABC123", "url": "https://example.test/start", "title": "untitled",
    }
    full = Chrome(32)
    try:
        ChromeBrowserAdapter(full, "alice", "g1").open_page("https://example.test/start")
    except Exception as exc:
        assert type(exc).__name__ == "BrowserUnavailable"
    else:
        raise AssertionError("tab limit was not enforced")
    assert all(not path.startswith("/json/new") for _, path in full.calls)
