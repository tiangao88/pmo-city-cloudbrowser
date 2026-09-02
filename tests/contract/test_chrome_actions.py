"""Contract tests for the owner-bound browser page-action adapter."""

from __future__ import annotations

from dataclasses import dataclass

from cloudbrowser.browser_slots import BrowserReadiness
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter


class FakeChrome:
    def json_request(self, path: str, *, method: str = "GET") -> object:
        if path == "/json/version":
            return {"Browser": "Chrome/128"}
        if path == "/json/list":
            return [{"type": "page", "url": "https://example.test", "id": "tab-1"}]
        return {"id": "new-tab"}

    def text_request(self, path: str, *, method: str = "GET") -> str:
        return "Closed"


@dataclass
class Actions:
    calls: list[tuple[str, object]]

    def navigate(self, url: str) -> None:
        self.calls.append(("navigate", url))

    def click(self, selector: str) -> None:
        self.calls.append(("click", selector))

    def type_text(self, selector: str, text: str) -> None:
        self.calls.append(("type", (selector, text)))

    def page_info(self, selector: str | None = None) -> dict[str, str]:
        return {"url": "https://example.test", "title": "Example", "text": "Hello"}


def test_chrome_adapter_exposes_injected_page_actions_only() -> None:
    actions = Actions([])
    adapter = ChromeBrowserAdapter(
        FakeChrome(),
        owner="owner@example.test",
        generation="generation-1",
        page_actions=actions,
    )
    adapter.navigate("https://example.test/next")
    adapter.click("#submit")
    adapter.type_text("#name", "Alice")
    assert adapter.page_info() == {"url": "https://example.test", "title": "Example", "text": "Hello"}
    assert actions.calls == [
        ("navigate", "https://example.test/next"),
        ("click", "#submit"),
        ("type", ("#name", "Alice")),
    ]


def test_chrome_adapter_has_no_page_action_fallback() -> None:
    adapter = ChromeBrowserAdapter(FakeChrome(), "owner@example.test", "generation-1")
    try:
        adapter.click("#submit")
    except Exception as exc:
        assert type(exc).__name__ == "BrowserUnavailable"
    else:
        raise AssertionError("missing page action adapter must fail closed")
