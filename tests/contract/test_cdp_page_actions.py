"""RED: real page actions for the deployed browser slot.

Decision 2026-09-08 (Tigo): milestone acceptance needs ``navigate`` and
``page_info`` working end-to-end through the viewer. The production
``build_browser_service`` currently leaves ``page_actions=None``, so every
agent page action fails closed with ``browser_unavailable``.

Design constraints (spec 33/W3, fail-closed by default):
- Only the local, service-owned Chrome DevTools HTTP endpoint is used as
  the navigation/target channel (``/json/new`` and ``/json/list``), the
  same surface the supervisor already relies on.
- Observed page state is captured through one CDP ``Runtime.evaluate``
  per request over a short-lived WebSocket, with a bounded JSON payload;
  no generic CDP passthrough is exposed to callers.
- Captured URL/title/text are re-validated by ``PageState`` upstream
  (agent_control) so nothing sensitive is echoed blindly; this adapter
  stays a dumb, bounded capture pipe.
"""

from __future__ import annotations

import json
import struct

import pytest

from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter
from cloudbrowser.browser_slots.transport import BrowserUnavailable


def _page_target(tab_id: str, url: str) -> dict[str, object]:
    return {
        "type": "page",
        "url": url,
        "id": tab_id,
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{tab_id}",
    }


class RecordingWebSocket:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self._sent = False

    def send(self, payload: str) -> None:
        self._sent = True
        self.commands.append(json.loads(payload)["method"])

    def recv(self) -> bytes:
        assert self._sent
        return json.dumps(
            {
                "id": 1,
                "result": {
                    "result": {
                        "value": {
                            "url": "https://example.test/",
                            "title": "",
                            "text": "",
                        }
                    }
                },
            }
        ).encode()

    def close(self) -> None:
        pass


def test_cdp_page_info_caps_websocket_timeout_to_remaining_deadline() -> None:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline

    chrome = _FakeChrome([_page_target("tab-1", "https://example.test/")])
    observed: list[float] = []
    websocket = RecordingWebSocket()
    adapter = CdpPageActionAdapter(
        chrome,
        ws_factory=lambda url, timeout_s: observed.append(timeout_s) or websocket,
    )
    deadline = BrokerDeadline(9.2, monotonic_clock=lambda: 9.0)

    adapter.page_info("tab-1", deadline=deadline)

    assert observed == [pytest.approx(0.2)]


class _FakeChrome:
    """Records DevTools HTTP calls the way ChromeHttpClient would."""

    def __init__(self, targets: list[dict[str, object]] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.targets = targets if targets is not None else [
            {"type": "page", "url": "about:blank", "id": "tab-1"}
        ]

    def json_request(self, path: str, *, method: str = "GET") -> object:
        self.calls.append((method, path))
        if path.startswith("/json/new"):
            self.targets.append({"type": "page", "url": "about:blank", "id": "tab-2"})
            return {"type": "page", "id": "tab-2", "url": "about:blank"}
        if path == "/json/list":
            return list(self.targets)
        return {"Browser": "Chrome/128"}

    def text_request(self, path: str, *, method: str = "GET") -> str:
        self.calls.append((method, path))
        return "Target is closing"


def test_navigate_drives_the_live_page_target_via_cdp_page_navigate() -> None:
    chrome = _FakeChrome(targets=[_page_target("tab-1", "about:blank")])
    ws = _FakeWebSocket(responses=[{"id": 1, "result": {}}])
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: ws)
    adapter.navigate("tab-1", "https://example.test/page")
    # The live tab is reused — no new target is created.
    assert not any(path.startswith("/json/new") for _, path in chrome.calls)
    sent = json.loads(ws.sent[0])
    assert sent["method"] == "Page.navigate"
    assert sent["params"]["url"] == "https://example.test/page"


def test_navigate_rejects_unknown_target_instead_of_creating_a_tab() -> None:
    chrome = _FakeChrome(targets=[])
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: _FakeWebSocket())
    with pytest.raises(BrowserUnavailable):
        adapter.navigate("tab-missing", "https://example.test/page")
    assert not any(path.startswith("/json/new") for _, path in chrome.calls)


def test_navigate_rejects_non_page_urls_before_touching_chrome() -> None:
    chrome = _FakeChrome()
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: _FakeWebSocket())
    bad_urls = (
        "ftp://example.test/x",
        "/etc/passwd",
        "http://u:p@example.test",
        "https://x.test/#frag",
    )
    for bad in bad_urls:
        with pytest.raises(ValueError):
            adapter.navigate("tab-1", bad)
    assert chrome.calls == []


def test_page_info_captures_url_title_and_text_via_cdp() -> None:
    chrome = _FakeChrome(targets=[_page_target("tab-9", "https://example.test/p")])
    ws = _FakeWebSocket(
        responses=[{"id": 1, "result": {"result": {"type": "string", "value": {
            "url": "https://example.test/p",
            "title": "Example Page",
            "text": "Hello world",
        }}}}]
    )
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: ws)
    info = adapter.page_info("tab-9")
    assert info == {"url": "https://example.test/p", "title": "Example Page", "text": "Hello world"}
    # The evaluate payload asks for location/title/body-text only, bounded.
    sent = json.loads(ws.sent[0])
    assert sent["method"] == "Runtime.evaluate"
    assert "document.title" in sent["params"]["expression"]
    assert sent["params"]["returnByValue"] is True


def test_page_info_is_bounded_and_fails_closed_without_a_page() -> None:
    chrome = _FakeChrome(targets=[{"type": "iframe", "url": "about:blank", "id": "x"}])
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: _FakeWebSocket())
    with pytest.raises(Exception) as excinfo:
        adapter.page_info("tab-1")
    assert type(excinfo.value).__name__ == "BrowserUnavailable"


def test_click_and_type_are_not_implemented_and_stay_fail_closed() -> None:
    chrome = _FakeChrome(targets=[_page_target("tab-1", "https://example.test/p")])
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: _FakeWebSocket())
    with pytest.raises(Exception) as excinfo:
        adapter.click("tab-1", "#submit")
    assert type(excinfo.value).__name__ == "BrowserUnavailable"
    with pytest.raises(Exception) as excinfo:
        adapter.type_text("tab-1", "#name", "Alice")
    assert type(excinfo.value).__name__ == "BrowserUnavailable"


def test_page_info_selector_argument_is_refused_for_now() -> None:
    """Normal agent actions do not gain the broker selector capability."""
    chrome = _FakeChrome(targets=[_page_target("tab-1", "https://example.test/p")])
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: _FakeWebSocket())
    with pytest.raises(ValueError):
        adapter.page_info("tab-1", "#some-selector")


def test_broker_rejects_unknown_target_before_opening_a_websocket() -> None:
    chrome = _FakeChrome(targets=[_page_target("target-present", "https://auth.example.test/")])
    opened: list[str] = []

    def ws_factory(url: str, timeout_s: float):
        opened.append(url)
        raise AssertionError("unknown target must be rejected before CDP")

    adapter = CdpPageActionAdapter(chrome, ws_factory=ws_factory)
    with pytest.raises(BrowserUnavailable):
        adapter.broker_page_info("target-missing", "#uid")
    assert opened == []


def test_broker_uses_requested_same_origin_target_for_selector_read() -> None:
    chrome = _FakeChrome(
        targets=[
            _page_target("target-other", "https://auth.example.test/other"),
            _page_target("target-requested", "https://auth.example.test/login"),
        ]
    )
    ws = _FakeWebSocket(
        responses=[
            {"id": 1, "result": {"result": {"type": "string", "value": {"found": True, "text": "uidField", "value": ""}}}}
        ]
    )
    selected: list[str] = []
    adapter = CdpPageActionAdapter(
        chrome,
        ws_factory=lambda url, timeout_s: (selected.append(url), ws)[1],
    )

    assert adapter.broker_page_info("target-requested", "#uid") == {
        "found": True,
        "text": "uidField",
        "value": "",
    }
    assert selected == ["ws://127.0.0.1:9222/devtools/page/target-requested"]
    command = json.loads(ws.sent[0])
    assert command["method"] == "Runtime.evaluate"
    assert command["params"]["returnByValue"] is True


def test_parser_caps_selector_result_size_independently() -> None:
    chrome = _FakeChrome(targets=[_page_target("target-1", "https://auth.example.test/login")])
    ws = _FakeWebSocket(
        responses=[
            {
                "id": 1,
                "result": {
                    "result": {
                        "type": "string",
                        "value": {"found": True, "text": "x" * 16385, "value": ""},
                    }
                },
            }
        ]
    )
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda _url, _timeout: ws)

    with pytest.raises(BrowserUnavailable):
        adapter.broker_page_info("target-1", "#uid")


def test_broker_click_and_type_are_distinct_from_normal_agent_actions() -> None:
    chrome = _FakeChrome(targets=[_page_target("target-1", "https://auth.example.test/login")])
    responses = [
        {"id": 1, "result": {"result": {"type": "string", "value": {"ok": True}}}},
        {"id": 1, "result": {"result": {"type": "string", "value": {"ok": True}}}},
    ]
    sockets: list[_FakeWebSocket] = []

    def ws_factory(url: str, timeout_s: float):
        socket = _FakeWebSocket(responses=[responses.pop(0)])
        sockets.append(socket)
        return socket

    adapter = CdpPageActionAdapter(chrome, ws_factory=ws_factory)
    adapter.broker_type_text("target-1", "#uid", "alice")
    adapter.broker_click("target-1", "button[type=submit]")
    assert [json.loads(socket.sent[0])["method"] for socket in sockets] == [
        "Runtime.evaluate",
        "Runtime.evaluate",
    ]


def test_evaluate_result_is_validated_not_echoed_blindly() -> None:
    chrome = _FakeChrome(targets=[_page_target("tab-9", "https://example.test/p")])  # no ws url
    bad = {"id": 1, "result": {"result": {"type": "string", "value": "not-a-dict"}}}
    ws = _FakeWebSocket(responses=[bad])
    adapter = CdpPageActionAdapter(chrome, ws_factory=lambda url, timeout_s: ws)
    with pytest.raises(Exception) as excinfo:
        adapter.page_info("tab-1")
    assert type(excinfo.value).__name__ == "BrowserUnavailable"


def test_build_browser_service_wires_the_real_page_actions(monkeypatch) -> None:
    """The production runtime must inject CdpPageActionAdapter, not None."""

    import cloudbrowser.browser_service as browser_service

    env = {
        "CB_INSTANCE_ID": "test-instance",
        "CB_RELEASE_VERSION": "test-release",
        "CB_PRINCIPAL_ID": "principal-unassigned",
        "CB_BINDING_GENERATION": "generation-0",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    captured: dict[str, object] = {}

    class _Probe:
        def __init__(self, *args, **kwargs):
            captured["probe"] = kwargs.get("probe")

        def readiness(self):
            return False

    real_adapter = browser_service.ChromeBrowserAdapter

    def spy_adapter(chrome, *, owner, generation, **kwargs):
        captured["page_actions"] = kwargs.get("page_actions")
        return real_adapter(chrome, owner=owner, generation=generation, **kwargs)

    monkeypatch.setattr(browser_service, "ChromeBrowserAdapter", spy_adapter)

    # Touch the construction path without binding a real port.

    class _FakeServer:
        def __init__(self, *args, **kwargs):
            pass

        def serve_forever(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(browser_service, "create_browser_server", lambda *a, **k: _FakeServer())
    fake_registry = type(
        "R",
        (),
        {
            "on_binding": staticmethod(lambda b: None),
            "attach_stop_event": lambda self, e: None,
            "close": lambda self: None,
        },
    )
    monkeypatch.setattr(browser_service, "DownloadWatcherRegistry", lambda: fake_registry)

    try:
        browser_service.build_browser_service()
    except Exception:
        pass  # construction details (ports) are irrelevant here
    actions = captured.get("page_actions")
    assert isinstance(actions, CdpPageActionAdapter)


def test_build_browser_service_wires_basic_auth_secret_gate(monkeypatch) -> None:
    """Production browser runtime must wire BasicAuthCapability + secret gate."""
    import cloudbrowser.browser_service as browser_service
    from cloudbrowser.browser_slots.basic_auth import BasicAuthCapability

    for key, value in {
        "CB_INSTANCE_ID": "test-instance",
        "CB_RELEASE_VERSION": "test-release",
        "CB_PRINCIPAL_ID": "principal-unassigned",
        "CB_BINDING_GENERATION": "generation-0",
        "CB_BROKER_SUBMIT_SECRET": "submit-secret-0123456789abcdef",
    }.items():
        monkeypatch.setenv(key, value)
    captured: dict[str, object] = {}

    class _FakeServer:
        def serve_forever(self):
            pass

        def server_close(self):
            pass

    def create_spy(*args, **kwargs):
        captured.update(kwargs)
        return _FakeServer()

    monkeypatch.setattr(browser_service, "create_browser_server", create_spy)
    fake_registry = type(
        "R",
        (),
        {
            "on_binding": staticmethod(lambda b: None),
            "attach_stop_event": lambda self, e: None,
            "close": lambda self: None,
        },
    )
    monkeypatch.setattr(browser_service, "DownloadWatcherRegistry", lambda: fake_registry)

    browser_service.build_browser_service()

    assert isinstance(captured["basic_auth"], BasicAuthCapability)
    assert captured["broker_submit_secret"] == "submit-secret-0123456789abcdef"


def test_handshake_request_target_never_ends_in_a_bare_question_mark() -> None:
    """Chrome 500s a DevTools WS handshake with a trailing '?' (live on dev01,
    2026-09-08): the target must omit the query separator when there is no
    query, or page_info fails closed with browser_unavailable."""

    class _RawSocket:
        def __init__(self, *args):
            self.sent: list[bytes] = []

        def settimeout(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def sendall(self, data):
            self.sent.append(data)

        def recv(self, size):
            # Handshake response, then a close frame.
            if len(self.sent) == 1:
                return b"HTTP/1.1 101 WebSocket Protocol Handshake\r\nUpgrade: websocket\r\n\r\n"
            return b"\x88\x02\x03\xe8"  # close frame

        def close(self):
            pass

    raw = _RawSocket()
    monkeypatch = __import__("pytest").MonkeyPatch()

    def fake_connect(address, timeout):
        return raw

    import cloudbrowser.browser_slots.page_actions as pa

    monkeypatch.setattr(pa.socket, "create_connection", fake_connect)
    ws = pa._WebSocket(
        "ws://127.0.0.1:9222/devtools/page/tab-1",
        open_timeout_s=2,
        command_timeout_s=2,
    )
    assert ws is not None
    first = raw.sent[0].decode("latin-1")
    request_line = first.split("\r\n")[0]
    assert "?" not in request_line, request_line
    assert "/devtools/page/tab-1 HTTP/1.1" in request_line
    monkeypatch.undo()


class _FakeWebSocket:
    """Minimal frame-level WebSocket double for the adapter's CDP session."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self.sent: list[str] = []
        self._responses = list(responses or [])

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def recv(self, _size: int = 65536) -> bytes:
        if not self._responses:
            return json.dumps({"id": 999, "result": {}}).encode()
        return json.dumps(self._responses.pop(0)).encode()

    def close(self) -> None:
        pass


def _ws_frame(payload: bytes) -> bytes:
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    return bytes(header) + payload
