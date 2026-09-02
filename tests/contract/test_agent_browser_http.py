"""Contract tests for the HTTP-backed restricted agent browser adapter."""

from __future__ import annotations

from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport


class FakeAgentClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def request(self, method: str, path: str, *, body: str | None = None) -> object:
        self.calls.append((method, path, body))
        if path == "/agent/readiness":
            return {"owner": "owner@example.test", "generation": "generation-1", "cdp_ok": True}
        if path == "/agent/pages":
            return {
                "pages": [
                    {"tab_id": "tab-1", "url": "https://example.test", "title": "Example"}
                ]
            }
        if path == "/agent/pages/info":
            return {"url": "https://example.test", "title": "Example", "text": "Hello"}
        return {"ok": True}


def test_http_agent_browser_composes_with_agent_transport() -> None:
    client = FakeAgentClient()
    transport = HttpAgentBrowserTransport(
        client,
        expected_owner="owner@example.test",
        expected_generation="generation-1",
    )
    browser = HttpAgentBrowser(transport)

    assert browser.readiness().cdp_ok is True
    assert browser.list_pages()[0]["tab_id"] == "tab-1"
    browser.navigate("https://example.test/next")
    browser.click("#submit")
    browser.type_text("#name", "Alice")
    assert browser.page_info() == {
        "url": "https://example.test",
        "title": "Example",
        "text": "Hello",
    }

    assert client.calls == [
        ("GET", "/agent/readiness", None),
        ("GET", "/agent/pages", None),
        ("POST", "/agent/pages/navigate", "https://example.test/next"),
        ("POST", "/agent/pages/click", "#submit"),
        ("POST", "/agent/pages/type", "#name\nAlice"),
        ("GET", "/agent/pages/info", None),
    ]
