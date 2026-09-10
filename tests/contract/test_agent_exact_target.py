"""RED tests for exact-target agent page actions and bounded page state."""

from __future__ import annotations

import json

import pytest

from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter
from cloudbrowser.browser_slots.transport import BrowserUnavailable


class _FakeWebSocket:
    def __init__(self, responses: list[dict]) -> None:
        self.sent: list[str] = []
        self._responses = list(responses)

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def recv(self, _size: int = 65536) -> bytes:
        return json.dumps(self._responses.pop(0)).encode("utf-8")

    def close(self) -> None:
        return None


class _FakeChrome:
    def __init__(self, targets: list[dict[str, object]]) -> None:
        self.targets = targets
        self.calls: list[tuple[str, str]] = []

    def json_request(self, path: str, *, method: str = "GET") -> object:
        self.calls.append((method, path))
        if path == "/json/list":
            return list(self.targets)
        raise AssertionError((method, path))


def _target(target_id: str, url: str) -> dict[str, object]:
    return {
        "type": "page",
        "id": target_id,
        "url": url,
        "title": target_id,
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
    }


def test_agent_navigate_uses_the_requested_target_not_the_first_tab() -> None:
    chrome = _FakeChrome(
        [
            _target("tab-a", "https://first.example.test/"),
            _target("tab-b", "https://second.example.test/"),
        ]
    )
    sockets: list[tuple[str, _FakeWebSocket]] = []

    def ws_factory(url: str, timeout_s: float) -> _FakeWebSocket:
        socket = _FakeWebSocket([{"id": 1, "result": {}}])
        sockets.append((url, socket))
        return socket

    adapter = CdpPageActionAdapter(chrome, ws_factory=ws_factory)

    adapter.navigate("tab-b", "https://destination.example.test/")

    assert [url for url, _ in sockets] == [
        "ws://127.0.0.1:9222/devtools/page/tab-b"
    ]
    command = json.loads(sockets[0][1].sent[0])
    assert command["method"] == "Page.navigate"
    assert command["params"] == {"url": "https://destination.example.test/"}


def test_agent_page_action_rejects_unknown_target_before_opening_websocket() -> None:
    chrome = _FakeChrome([_target("tab-a", "https://first.example.test/")])
    opened: list[str] = []

    def ws_factory(url: str, timeout_s: float) -> _FakeWebSocket:
        opened.append(url)
        raise AssertionError("unknown target must not open a websocket")

    adapter = CdpPageActionAdapter(chrome, ws_factory=ws_factory)

    with pytest.raises(BrowserUnavailable):
        adapter.navigate("tab-missing", "https://destination.example.test/")

    assert opened == []
