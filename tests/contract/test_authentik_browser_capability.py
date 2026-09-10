"""Contract tests for the secret-gated Authentik browser surface."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.browser_slots.authentik import AuthentikCapability
from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.browser_slots.page_actions import (
    CdpPageActionAdapter,
    _authentik_rejection_expression,
    _parse_authentik_rejection,
)
from cloudbrowser.browser_slots.transport import BrowserUnavailable
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded


def test_authentik_capability_honors_shared_deadline_before_page_probe() -> None:
    class NeverCalled:
        def broker_page_info(self, *args, **kwargs):
            raise AssertionError("page probe must not start after deadline")

    capability = AuthentikCapability(
        NeverCalled(),
        ("https://auth.example.test",),
        ("https://app.example.test",),
        ("/home",),
        deadline=BrokerDeadline(2.0, monotonic_clock=lambda: 3.0),
    )

    with pytest.raises(BrokerDeadlineExceeded):
        capability.state(target_id="target-1")



_SECRET = "submit-secret-0123456789abcdef"


class _Adapter:
    def readiness(self):
        return type(
            "R",
            (),
            {
                "owner": "pmo-a",
                "generation": "g1",
                "cdp_ok": True,
            },
        )()


class _Process:
    state = "ready"
    def readiness(self): return True


class _Authentik:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def state(self, *, target_id: str) -> dict[str, str | None]:
        self.calls.append(("state", target_id))
        return {"stage": "mfa", "modality": "totp", "url": "https://auth.example.test/"}

    def begin(self, *, target_id: str, entry_url: str) -> None:
        self.calls.append(("begin", (target_id, entry_url)))

    def identification(
        self, *, target_id: str, username: str, password: str
    ) -> dict[str, str]:
        self.calls.append(("identification", (target_id, username, password)))
        return {"outcome": "submitted"}

    def proof(self, *, target_id: str) -> dict[str, str | None]:
        self.calls.append(("proof", target_id))
        return {"account": None}


class _FakeChrome:
    def __init__(self, targets):
        self.targets = targets

    def json_request(self, path, *, method="GET"):
        assert path == "/json/list"
        return self.targets


class _FakeWebSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        return json.dumps(self.responses.pop(0)).encode()

    def close(self):
        pass


def _target(target_id: str, url: str) -> dict[str, str]:
    return {
        "id": target_id,
        "type": "page",
        "url": url,
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
    }


def test_explicit_rejection_probe_returns_only_a_bounded_state() -> None:
    expression = _authentik_rejection_expression(
        expected_origins=("https://auth.example.test",),
        rejected_selector="ak-flow-executor [role=alert]",
    )
    assert "textContent" not in expression
    assert "innerText" not in expression
    assert "location.search" not in expression
    assert "location.hash" not in expression
    assert "role=alert" not in repr(
        _parse_authentik_rejection(
            {"result": {"value": {"state": "rejected"}}}
        )
    )
    assert _parse_authentik_rejection(
        {"result": {"value": {"state": "rejected"}}}
    ) == {"state": "rejected"}


def test_authentik_capability_rejects_missing_target_before_credentials() -> None:
    chrome = _FakeChrome([_target("target-present", "https://auth.example.test/login")])
    credential_operations: list[str] = []

    def ws_factory(url, timeout):
        credential_operations.append(url)
        raise AssertionError("unknown target must not open CDP")

    actions = CdpPageActionAdapter(chrome, ws_factory=ws_factory)
    capability = AuthentikCapability(
        actions,
        ("https://auth.example.test",),
        (),
        (),
    )
    with pytest.raises(BrowserUnavailable):
        capability.identification(
            target_id="target-missing", username="alice", password="secret-pw"
        )
    assert credential_operations == []


def test_authentik_capability_selects_requested_same_origin_target() -> None:
    chrome = _FakeChrome(
        [
            _target("target-other", "https://auth.example.test/other"),
            _target("target-requested", "https://auth.example.test/login"),
        ]
    )
    sockets: list[str] = []
    ws = _FakeWebSocket(
        [
            {"id": 1, "result": {"result": {"value": {"url": "https://auth.example.test/login", "title": "", "text": ""}}}},
            {"id": 1, "result": {"result": {"value": {"found": False, "text": "", "value": ""}}}},
            {"id": 1, "result": {"result": {"value": {"found": True, "text": "", "value": ""}}}},
        ]
    )
    actions = CdpPageActionAdapter(
        chrome,
        ws_factory=lambda url, timeout: (sockets.append(url), ws)[1],
    )
    capability = AuthentikCapability(
        actions,
        ("https://auth.example.test",),
        (),
        (),
    )
    assert capability.state(target_id="target-requested")["stage"] == "identification"
    assert sockets == ["ws://127.0.0.1:9222/devtools/page/target-requested"] * 3


class _FakeAuthentikActions:
    def __init__(self):
        self.stage = "identification"
        self.calls = []

    def broker_page_info(self, target_id: str, selector: str | None = None):
        return {"url": "https://auth.example.test/login", "title": "", "text": ""} if selector is None else {"found": False, "text": "", "value": ""}

    def broker_authentik_mfa(self, target_id: str, **kwargs):
        return {"found": self.stage == "mfa", "device_class": "totp" if self.stage == "mfa" else None}

    def broker_authentik_identification(self, target_id, **kwargs):
        self.calls.append(("transaction", target_id, kwargs["username"]))
        self.stage = "mfa"
        return {"stage": "submitted", "url": "https://auth.example.test/login"}

    def broker_authentik_rejection(self, target_id, **kwargs):
        self.calls.append(("rejection", target_id))
        return {"state": "clear"}

    def broker_authentik_proof(self, target_id, **kwargs):
        return {"account": None}

    def broker_type_text(self, target_id, selector, text):
        self.calls.append(("type", target_id, selector, text))

    def broker_click(self, target_id, selector):
        self.calls.append(("click", target_id, selector))
        self.stage = "mfa"

    def broker_navigate(self, target_id, url):
        self.calls.append(("navigate", target_id, url))


def test_authentik_identification_transitions_to_mfa_required_state() -> None:
    actions = _FakeAuthentikActions()
    capability = AuthentikCapability(
        actions,
        ("https://auth.example.test",),
        (),
        (),
        stage_timeout_s=0.2,
        poll_interval_s=0.01,
    )
    assert capability.identification(
        target_id="target-requested", username="alice", password="secret-pw"
    ) == {"outcome": "submitted"}
    assert capability.state(target_id="target-requested") == {
        "stage": "mfa",
        "modality": "totp",
        "url": "https://auth.example.test/login",
    }
    assert [call[0] for call in actions.calls][:2] == [
        "transaction",
        "rejection",
    ]
    assert "click" not in [call[0] for call in actions.calls]


def _post(port: int, path: str, secret: str) -> tuple[int, dict]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps({"target_id": "target-1"}).encode(),
        method="POST",
        headers={"X-CB-Broker-Secret": secret},
    )
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())
    return response.status, json.loads(response.read())


def test_authentik_surface_is_secret_gated_and_status_only() -> None:
    server = create_browser_server(
        _Adapter(),
        _Process(),
        instance_id="test",
        release_version="test",
        address=("127.0.0.1", 0),
        authentik=_Authentik(),
        broker_submit_secret=_SECRET,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _post(server.server_address[1], "/broker/authentik/state", "wrong")[0] == 401
        status, body = _post(server.server_address[1], "/broker/authentik/state", _SECRET)
        assert status == 200
        assert body == {
            "stage": "mfa",
            "modality": "totp",
            "url": "https://auth.example.test/",
        }
        assert not any(key in body for key in ("password", "cookie", "token", "headers"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
