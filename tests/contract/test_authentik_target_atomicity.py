"""Exact-target and atomic Authentik browser contracts."""

from __future__ import annotations

import json
import threading
import time

import pytest

from cloudbrowser.browser_slots.authentik import AuthentikCapability
from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter
from cloudbrowser.browser_slots.transport import BrowserUnavailable


class _Chrome:
    def __init__(self, targets: list[dict[str, str]]) -> None:
        self.targets = targets

    def json_request(self, path: str, *, method: str = "GET") -> object:
        assert (method, path) == ("GET", "/json/list")
        return self.targets


def _target(target_id: str, url: str) -> dict[str, str]:
    return {
        "id": target_id,
        "type": "page",
        "url": url,
        "title": target_id,
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
    }


class _Ws:
    def __init__(self, response_values: list[object], events: list[str]) -> None:
        self._values = list(response_values)
        self._events = events
        self._last: dict[str, object] | None = None

    def send(self, payload: str) -> None:
        self._last = json.loads(payload)
        self._events.append(str(self._last["method"]))

    def recv(self) -> bytes:
        assert self._last is not None
        return json.dumps(
            {"id": self._last["id"], "result": {"result": {"value": self._values.pop(0)}}}
        ).encode()

    def close(self) -> None:
        pass


def test_identification_is_one_exact_target_transaction() -> None:
    events: list[str] = []
    transaction_result = {
        "stage": "submitted",
        "url": "https://auth.example.test/if/flow/default-authentication-flow/",
    }

    class Actions:
        polls = 0

        def broker_authentik_identification(self, target_id, **kwargs):
            events.append(target_id)
            assert kwargs == {
                "expected_origins": ("https://auth.example.test",),
                "username_selector": (
                    "ak-flow-executor ak-stage-identification input[name=uidField]"
                ),
                "password_selector": (
                    "ak-flow-executor ak-stage-identification "
                    "ak-flow-input-password input[name=password]"
                ),
                "submit_selector": (
                    "ak-flow-executor ak-stage-identification button[type=submit]"
                ),
                "rejected_selector": "ak-flow-executor ak-stage-identification [role=alert]",
                "username": "alice",
                "password": "secret-pw",
            }
            return transaction_result

        def broker_authentik_rejection(self, target_id, **kwargs):
            assert target_id == "target-exact"
            return {"state": "clear"}

        def broker_page_info(self, target_id, selector=None):
            if selector is None:
                return {
                    "url": "https://app.example.test/authenticated?secret=yes#fragment",
                    "title": "",
                    "text": "",
                }
            return {"found": False, "text": "", "value": ""}

    capability = AuthentikCapability(
        Actions(),
        ("https://auth.example.test",),
        ("https://app.example.test",),
        ("/authenticated",),
        stage_timeout_s=0.2,
        poll_interval_s=0.01,
    )
    assert capability.identification(
        target_id="target-exact", username="alice", password="secret-pw"
    ) == {"outcome": "submitted"}
    assert events == ["target-exact"]


def test_normal_navigation_cannot_interleave_with_identification_transaction() -> None:
    started = threading.Event()
    release = threading.Event()
    events: list[str] = []
    chrome = _Chrome([_target("target-exact", "https://auth.example.test/login")])

    class BlockingWs:
        def __init__(self) -> None:
            self.message: dict[str, object] | None = None

        def send(self, payload: str) -> None:
            self.message = json.loads(payload)
            expression = str(self.message.get("params", {}).get("expression", ""))
            if "cloudbrowser-authentik-identification" in expression:
                events.append("identification-start")
                started.set()
                assert release.wait(1)
                events.append("identification-end")
            else:
                events.append("navigate")

        def recv(self) -> bytes:
            assert self.message is not None
            if self.message["method"] == "Runtime.evaluate":
                value: object = {
                    "stage": "submitted",
                    "url": "https://auth.example.test/login",
                }
            else:
                value = None
            return json.dumps(
                {"id": self.message["id"], "result": {"result": {"value": value}}}
            ).encode()

        def close(self) -> None:
            pass

    actions = CdpPageActionAdapter(chrome, ws_factory=lambda _url, _timeout: BlockingWs())
    identification = threading.Thread(
        target=lambda: actions.broker_authentik_identification(
            "target-exact",
            expected_origins=("https://auth.example.test",),
            username_selector="input[name=uidField]",
            password_selector="input[name=password]",
            submit_selector="button[type=submit]",
            rejected_selector="[role=alert]",
            username="alice",
            password="secret-pw",
        )
    )
    identification.start()
    assert started.wait(1)
    navigation = threading.Thread(target=lambda: actions.navigate("target-exact", "https://example.test/next"))
    navigation.start()
    time.sleep(0.03)
    assert events == ["identification-start"]
    release.set()
    identification.join(1)
    navigation.join(1)
    assert events == ["identification-start", "identification-end", "navigate"]


def test_identification_only_rejects_on_explicit_rejected_signal() -> None:
    class Actions:
        calls = 0

        def broker_authentik_identification(self, target_id, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"stage": "submitted", "url": "https://auth.example.test/flow"}
            return {"stage": "not_ready", "url": "https://auth.example.test/flow"}

        def broker_authentik_rejection(self, target_id, **kwargs):
            return {"state": "clear"}

        def broker_page_info(self, target_id, selector=None):
            if selector is None:
                return {"url": "https://auth.example.test/flow", "title": "", "text": ""}
            return {"found": False, "text": "", "value": ""}

        def broker_navigate(self, target_id, url):
            raise AssertionError((target_id, url))

        def broker_click(self, target_id, selector):
            raise AssertionError((target_id, selector))

        def broker_type_text(self, target_id, selector, text):
            raise AssertionError((target_id, selector, text))

        def broker_authentik_proof(self, target_id, **kwargs):
            return {"account": None}

    capability = AuthentikCapability(
        Actions(),
        ("https://auth.example.test",),
        (),
        (),
        stage_timeout_s=0.03,
        poll_interval_s=0.01,
    )
    with pytest.raises(BrowserUnavailable, match="transition timed out"):
        capability.identification(
            target_id="target-exact", username="alice", password="secret-pw"
        )


def test_state_strips_query_and_fragment_from_internal_url() -> None:
    class Actions:
        def broker_page_info(self, target_id, selector=None):
            if selector is None:
                return {
                    "url": "https://app.example.test/authenticated?token=hidden#private",
                    "title": "",
                    "text": "",
                }
            return {"found": False, "text": "", "value": ""}

        def broker_navigate(self, target_id, url):
            raise AssertionError((target_id, url))

        def broker_click(self, target_id, selector):
            raise AssertionError((target_id, selector))

        def broker_type_text(self, target_id, selector, text):
            raise AssertionError((target_id, selector, text))

        def broker_authentik_identification(self, target_id, **kwargs):
            raise AssertionError((target_id, kwargs))

        def broker_authentik_rejection(self, target_id, **kwargs):
            raise AssertionError((target_id, kwargs))

        def broker_authentik_proof(self, target_id, **kwargs):
            return {"account": None}

    capability = AuthentikCapability(
        Actions(),
        ("https://auth.example.test",),
        ("https://app.example.test",),
        ("/authenticated",),
    )
    assert capability.state(target_id="target-exact") == {
        "stage": "application",
        "modality": None,
        "url": "https://app.example.test/authenticated",
    }
