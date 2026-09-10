"""RED/contract tests for broker-only CDP HTTP Basic capability."""

from __future__ import annotations

import json

import pytest

from cloudbrowser.browser_slots.basic_auth import BasicAuthCapability
from cloudbrowser.browser_slots.transport import BrowserUnavailable
from cloudbrowser.credential_broker.deadline import BrokerDeadline



class FakeChrome:
    def __init__(
        self,
        url: str = "https://basic.example.test/protected",
        *,
        target_id: str = "target-1",
    ) -> None:
        self.url = url
        self.target_id = target_id
        self.targets: list[dict[str, str]] | None = None

    def json_request(self, path: str, *, method: str = "GET") -> object:
        assert path == "/json/list"
        return self.targets or [
            {
                "id": self.target_id,
                "type": "page",
                "url": self.url,
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1",
            }
        ]


class FakeWebSocket:
    def __init__(self, chrome: FakeChrome, events: list[dict[str, object]]) -> None:
        self.chrome = chrome
        self.events = list(events)
        self.sent: list[dict[str, object]] = []
        self.closed = False

    def send(self, payload: str) -> None:
        message = json.loads(payload)
        self.sent.append(message)
        if message["method"] == "Fetch.continueWithAuth":
            response = message["params"]["authChallengeResponse"]
            if response["response"] == "ProvideCredentials":
                self.chrome.url = "https://basic.example.test/home"

    def recv(self) -> bytes:
        if not self.events:
            raise TimeoutError("no more events")
        return json.dumps(self.events.pop(0)).encode()

    def close(self) -> None:
        self.closed = True


class DeadlineWebSocket(FakeWebSocket):
    def __init__(self, chrome: FakeChrome, events: list[dict[str, object]], clock: list[float]) -> None:
        super().__init__(chrome, events)
        self.clock = clock

    def recv(self) -> bytes:
        self.clock[0] = 5.0
        return super().recv()


def test_basic_capability_checks_shared_deadline_inside_event_loop() -> None:
    chrome = FakeChrome()
    clock = [1.0]
    ws = DeadlineWebSocket(chrome, [_auth_event()], clock)
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)
    deadline = BrokerDeadline(2.0, monotonic_clock=lambda: clock[0])

    with pytest.raises(TimeoutError, match="deadline"):
        capability.probe(target_id=_target_id(chrome), deadline=deadline)


def test_basic_probe_checks_deadline_after_target_lookup_before_websocket() -> None:
    clock = [1.0]

    class SlowChrome(FakeChrome):
        lookups = 0

        def json_request(self, path: str, *, method: str = "GET") -> object:
            self.lookups += 1
            if self.lookups == 2:
                clock[0] = 5.0
            return super().json_request(path, method=method)

    chrome = SlowChrome()
    ws_opened = False

    def ws_factory(url, timeout):  # noqa: ANN001
        nonlocal ws_opened
        ws_opened = True
        raise AssertionError("expired target lookup must not open websocket")

    capability = BasicAuthCapability(chrome, ws_factory=ws_factory)
    with pytest.raises(TimeoutError, match="deadline"):
        capability.probe(
            target_id=_target_id(chrome),
            deadline=BrokerDeadline(2.0, monotonic_clock=lambda: clock[0]),
        )
    assert ws_opened is False


def test_basic_submit_does_not_send_cdp_command_after_receive_deadline() -> None:
    chrome = FakeChrome()
    clock = [1.0]
    ws = DeadlineWebSocket(
        chrome,
        [
            {
                "method": "Fetch.requestPaused",
                "params": {"requestId": "late-request"},
            }
        ],
        clock,
    )
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)

    with pytest.raises(TimeoutError, match="deadline"):
        capability.submit(
            "https://basic.example.test",
            "alice",
            "secret-pw",
            target_id=_target_id(chrome),
            success_path="/home",
            deadline=BrokerDeadline(2.0, monotonic_clock=lambda: clock[0]),
        )
    assert not any(message["method"] == "Fetch.continueRequest" for message in ws.sent)


def _auth_event(origin: str = "https://basic.example.test") -> dict[str, object]:
    return {
        "method": "Fetch.authRequired",
        "params": {
            "requestId": "fetch-1",
            "request": {"url": origin + "/protected"},
            "authChallenge": {"scheme": "Basic", "origin": origin, "realm": "local"},
        },
    }


def _target_id(chrome: FakeChrome) -> str:
    return chrome.target_id


def test_capability_handles_one_matching_basic_challenge() -> None:
    chrome = FakeChrome()
    ws = FakeWebSocket(chrome, [_auth_event(), {"method": "Page.loadEventFired", "params": {}}])
    capability = BasicAuthCapability(
        chrome, ws_factory=lambda url, timeout: ws
    )
    capability.observe_challenge("https://basic.example.test")

    capability.submit(
        "https://basic.example.test",
        "alice",
        "secret-pw",
        target_id=_target_id(chrome),
        success_path="/home",
    )

    assert capability.state(target_id=_target_id(chrome)) == {
        "url": "https://basic.example.test/home",
        "challenge_origin": None,
        "application_authenticated": True,
    }
    auth_commands = [m for m in ws.sent if m["method"] == "Fetch.continueWithAuth"]
    assert auth_commands == [
        {
            "id": 4,
            "method": "Fetch.continueWithAuth",
            "params": {
                "requestId": "fetch-1",
                "authChallengeResponse": {
                    "response": "ProvideCredentials",
                    "username": "alice",
                    "password": "secret-pw",
                },
            },
        }
    ]
    assert ws.closed is True


def test_capability_cancels_foreign_origin_without_credentials() -> None:
    chrome = FakeChrome()
    ws = FakeWebSocket(
        chrome,
        [_auth_event("https://evil.example.test")],
    )
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)
    capability.observe_challenge("https://basic.example.test")

    with pytest.raises(BrowserUnavailable):
        capability.submit(
            "https://basic.example.test",
            "alice",
            "secret-pw",
            target_id=_target_id(chrome),
            success_path="/home",
        )

    serialized = json.dumps(
        [m for m in ws.sent if m["method"] == "Fetch.continueWithAuth"]
    )
    assert "secret-pw" not in serialized
    assert "CancelAuth" in serialized


def test_capability_probe_reports_a_real_challenge_without_credentials() -> None:
    chrome = FakeChrome()
    ws = FakeWebSocket(chrome, [_auth_event()])
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)

    state = capability.probe(target_id=_target_id(chrome))

    assert state == {
        "url": "https://basic.example.test/protected",
        "challenge_origin": "https://basic.example.test",
        "application_authenticated": False,
    }
    cancel_commands = [
        m for m in ws.sent if m["method"] == "Fetch.continueWithAuth"
    ]
    assert cancel_commands[0]["params"]["authChallengeResponse"] == {
        "response": "CancelAuth"
    }
    assert "password" not in json.dumps(ws.sent).lower()


def test_capability_probe_redacts_query_and_fragment_from_public_state() -> None:
    chrome = FakeChrome("https://basic.example.test/protected?code=secret#state")
    ws = FakeWebSocket(chrome, [_auth_event()])
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)

    state = capability.probe(target_id=_target_id(chrome))

    assert state["url"] == "https://basic.example.test/protected"
    assert capability._state.url == "https://basic.example.test/protected?code=secret#state"


def test_capability_state_rejects_userinfo_and_bounds_redacted_url() -> None:
    for url in (
        "https://user:password@basic.example.test/protected",
        "https://basic.example.test/" + "a" * 2048,
    ):
        chrome = FakeChrome(url)
        capability = BasicAuthCapability(chrome, ws_factory=lambda _url, _timeout: None)
        with pytest.raises(BrowserUnavailable):
            capability.state(target_id=_target_id(chrome))


@pytest.mark.parametrize(
    "websocket_url",
    (
        "ws://192.0.2.1:9222/devtools/page/1",
        "ws://user:password@127.0.0.1:9222/devtools/page/1",
        "ws://127.0.0.1/devtools/page/1",
        "ws://127.0.0.1:not-a-port/devtools/page/1",
        "ws://127.0.0.1:9222/devtools/page/1#fragment",
        "wss://127.0.0.1:9222/devtools/page/1",
    ),
)
def test_page_websocket_revalidates_the_local_endpoint(websocket_url: str) -> None:
    chrome = FakeChrome()
    chrome.targets = [
        {
            "id": chrome.target_id,
            "type": "page",
            "url": chrome.url,
            "webSocketDebuggerUrl": websocket_url,
        }
    ]
    capability = BasicAuthCapability(chrome, ws_factory=lambda _url, _timeout: None)

    with pytest.raises(BrowserUnavailable):
        capability._page_websocket(chrome.target_id)


def test_capability_reports_a_second_matching_challenge_for_broker_failure() -> None:
    chrome = FakeChrome()
    ws = FakeWebSocket(chrome, [_auth_event(), _auth_event()])
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)
    capability.observe_challenge("https://basic.example.test")

    capability.submit(
        "https://basic.example.test",
        "alice",
        "secret-pw",
        target_id=_target_id(chrome),
        success_path="/home",
    )

    state = capability.state(target_id=_target_id(chrome))
    assert state["challenge_origin"] == "https://basic.example.test"
    assert state["application_authenticated"] is False
    auth_commands = [
        m for m in ws.sent if m["method"] == "Fetch.continueWithAuth"
    ]
    assert auth_commands[0]["params"]["authChallengeResponse"]["response"] == "ProvideCredentials"
    assert auth_commands[1]["params"]["authChallengeResponse"] == {
        "response": "CancelAuth"
    }


def test_capability_rejects_unknown_target_before_cdp() -> None:
    chrome = FakeChrome(target_id="target-1")
    used = False

    def ws_factory(url, timeout):  # noqa: ANN001
        nonlocal used
        used = True
        raise AssertionError("should not open websocket")

    capability = BasicAuthCapability(chrome, ws_factory=ws_factory)
    with pytest.raises(BrowserUnavailable):
        capability.submit(
            "https://basic.example.test",
            "alice",
            "secret-pw",
            target_id="target-missing",
            success_path="/home",
        )
    assert used is False


def test_capability_uses_exact_target_when_origins_match() -> None:
    chrome = FakeChrome()
    chrome.targets = [
        {
            "id": "target-other",
            "type": "page",
            "url": "https://basic.example.test/other",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/other",
        },
        {
            "id": "target-requested",
            "type": "page",
            "url": "https://basic.example.test/protected",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/requested",
        },
    ]
    selected: list[str] = []
    ws = FakeWebSocket(chrome, [_auth_event()])
    capability = BasicAuthCapability(
        chrome,
        ws_factory=lambda url, timeout: (selected.append(url), ws)[1],
    )

    capability.submit(
        "https://basic.example.test",
        "alice",
        "secret-pw",
        target_id="target-requested",
        success_path="/home",
    )

    assert selected == ["ws://127.0.0.1:9222/devtools/page/requested"]


def test_capability_requires_explicit_success_proof() -> None:
    chrome = FakeChrome()
    ws = FakeWebSocket(chrome, [_auth_event()])
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)

    capability.submit(
        "https://basic.example.test",
        "alice",
        "secret-pw",
        target_id="target-1",
        success_path="/account",
    )

    state = capability.state(target_id="target-1")
    assert state["application_authenticated"] is False


def test_capability_accepts_declared_success_path() -> None:
    chrome = FakeChrome()
    ws = FakeWebSocket(chrome, [_auth_event()])
    original_send = ws.send

    def send(payload: str) -> None:
        original_send(payload)
        message = json.loads(payload)
        if message["method"] == "Fetch.continueWithAuth":
            response = message["params"]["authChallengeResponse"]
            if response["response"] == "ProvideCredentials":
                chrome.url = "https://basic.example.test/account"

    ws.send = send  # type: ignore[method-assign]
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: ws)

    capability.submit(
        "https://basic.example.test",
        "alice",
        "secret-pw",
        target_id="target-1",
        success_path="/account",
    )

    state = capability.state(target_id="target-1")
    assert state["application_authenticated"] is True


def test_capability_rejects_wrong_current_origin_before_cdp() -> None:
    chrome = FakeChrome("https://other.example.test/protected")
    used = False

    def ws_factory(url, timeout):  # noqa: ANN001
        nonlocal used
        used = True
        raise AssertionError("should not open websocket")

    capability = BasicAuthCapability(chrome, ws_factory=ws_factory)
    with pytest.raises(ValueError):
        capability.submit(
            "https://basic.example.test",
            "alice",
            "secret-pw",
            target_id=_target_id(chrome),
            success_path="/home",
        )
    assert used is False


def test_capability_rejects_control_characters() -> None:
    chrome = FakeChrome()
    capability = BasicAuthCapability(chrome, ws_factory=lambda url, timeout: None)
    with pytest.raises(ValueError):
        capability.submit(
            "https://basic.example.test",
            "alice\r\nX: y",
            "pw",
            target_id=_target_id(chrome),
            success_path="/home",
        )
