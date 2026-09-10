"""Contract tests for the HTTP-backed restricted agent browser adapter."""

from __future__ import annotations

import json

from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport


class FakeAgentClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def request(self, method: str, path: str, *, body: str | None = None) -> object:
        self.calls.append((method, path, body))
        if path == "/agent/readiness":
            return {
                "profile_id": "profile-unassigned",
                "owner": "owner@example.test",
                "browser_id": "browser-unassigned",
                "generation": "generation-1",
                "cdp_ok": True,
            }
        if path == "/agent/pages":
            return {"pages": [{"tab_id": "tab-1", "url": "https://example.test", "title": "Example"}]}
        if path.startswith("/agent/pages/info?"):
            return {"url": "https://example.test", "title": "Example", "text": "Hello"}
        return {"ok": True}


def test_http_agent_browser_encodes_exact_target_page_info_route() -> None:
    client = FakeAgentClient()
    transport = HttpAgentBrowserTransport(client, expected_owner="owner@example.test", expected_generation="generation-1")

    assert transport.page_info("tab-1", "main [role=article]") == {
        "url": "https://example.test", "title": "Example", "text": "Hello"
    }
    assert client.calls == [
        ("GET", "/agent/pages/info?target_tab_id=tab-1&selector=main%20%5Brole%3Darticle%5D", None)
    ]


def test_http_agent_browser_composes_with_exact_target_transport() -> None:
    client = FakeAgentClient()
    transport = HttpAgentBrowserTransport(client, expected_owner="owner@example.test", expected_generation="generation-1")
    browser = HttpAgentBrowser(transport)

    assert browser.readiness().cdp_ok is True
    assert browser.list_pages()[0]["tab_id"] == "tab-1"
    browser.navigate("tab-1", "https://example.test/next")
    browser.click("tab-1", "#submit")
    browser.type_text("tab-1", "#name", "Alice")
    assert browser.page_info("tab-1") == {
        "url": "https://example.test", "title": "Example", "text": "Hello"
    }
    assert client.calls == [
        ("GET", "/agent/readiness", None),
        ("GET", "/agent/pages", None),
        ("POST", "/agent/pages/navigate", json.dumps({"target_tab_id": "tab-1", "value": "https://example.test/next"}, separators=(",", ":"))),
        ("POST", "/agent/pages/click", json.dumps({"target_tab_id": "tab-1", "value": "#submit"}, separators=(",", ":"))),
        ("POST", "/agent/pages/type", json.dumps({"target_tab_id": "tab-1", "selector": "#name", "text": "Alice"}, separators=(",", ":"))),
        ("GET", "/agent/pages/info?target_tab_id=tab-1", None),
    ]
