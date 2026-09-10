"""Focused RED contracts for Authentik/browser security remediations."""

from __future__ import annotations

import base64
import hashlib
import json
import struct

import pytest

from cloudbrowser.browser_slots.authentik import AuthentikCapability
from cloudbrowser.browser_slots.page_actions import (
    CdpPageActionAdapter,
    _WebSocket,
    bounded_page_targets,
)
from cloudbrowser.browser_slots.transport import BrowserUnavailable


class _MfaActions:
    def __init__(self, device_class: object) -> None:
        self.device_class = device_class

    def broker_page_info(self, target_id: str, selector: str | None = None):
        if selector is None:
            return {"url": "https://auth.example.test/login", "title": "", "text": ""}
        raise AssertionError("MFA state must use structured challenge metadata")

    def broker_authentik_mfa(self, target_id: str, **kwargs):
        return {"found": True, "device_class": self.device_class}


@pytest.mark.parametrize(
    "device_class, expected",
    [
        ("totp", "totp"),
        ("webauthn", "unknown"),
        ("email", "unknown"),
        ("sms", "unknown"),
        ("totpish", "unknown"),
        (None, "unknown"),
    ],
)
def test_authentik_mfa_requires_exact_device_class(device_class: object, expected: str) -> None:
    capability = AuthentikCapability(
        _MfaActions(device_class),
        ("https://auth.example.test",),
        (),
        (),
    )
    assert capability.state(target_id="target-1") == {
        "stage": "mfa",
        "modality": expected,
        "url": "https://auth.example.test/login",
    }


def test_public_page_targets_redact_query_and_fragment_but_broker_state_stays_raw() -> None:
    raw = [
        {
            "type": "page",
            "id": "target-1",
            "url": "https://app.example.test/callback?code=secret#state",
            "title": "callback",
        }
    ]
    assert bounded_page_targets(raw) == [
        {
            "tab_id": "target-1",
            "url": "https://app.example.test/callback",
            "title": "callback",
        }
    ]


def test_public_page_info_redacts_query_and_fragment() -> None:
    class Chrome:
        def json_request(self, path: str, *, method: str = "GET") -> object:
            assert path == "/json/list"
            return [
                {
                    "type": "page",
                    "id": "target-1",
                    "url": "https://app.example.test/callback?code=secret#state",
                    "title": "callback",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
                }
            ]

    class WebSocket:
        def send(self, payload: str) -> None:
            pass

        def recv(self) -> bytes:
            return json.dumps(
                {
                    "id": 1,
                    "result": {
                        "result": {
                            "value": {
                                "url": "https://app.example.test/callback?code=secret#state",
                                "title": "callback",
                                "text": "ok",
                            }
                        }
                    },
                }
            ).encode()

        def close(self) -> None:
            pass

    adapter = CdpPageActionAdapter(Chrome(), ws_factory=lambda _url, _timeout: WebSocket())
    assert adapter.page_info("target-1")["url"] == "https://app.example.test/callback"


class _RawSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []
        self.reads = 0

    def settimeout(self, timeout: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, size: int) -> bytes:
        self.reads += 1
        if self.reads == 1:
            return self.response
        return b""

    def close(self) -> None:
        pass


def _accept(key: str) -> str:
    return base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
    ).decode()


def test_websocket_handshake_rejects_wrong_sec_websocket_accept(monkeypatch) -> None:
    raw = _RawSocket(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: wrong\r\n\r\n"
    )
    monkeypatch.setattr(
        "cloudbrowser.browser_slots.page_actions.socket.create_connection",
        lambda _address, timeout: raw,
    )
    with pytest.raises(BrowserUnavailable):
        _WebSocket(
            "ws://127.0.0.1:9222/devtools/page/target-1",
            open_timeout_s=1,
            command_timeout_s=1,
        )


def test_websocket_rejects_binary_and_fragmented_frames() -> None:
    class Socket:
        def __init__(self, frame: bytes) -> None:
            self.frame = frame
            self.used = False

        def recv(self, size: int) -> bytes:
            if self.used:
                return b""
            self.used = True
            return self.frame

        def sendall(self, data: bytes) -> None:
            pass

        def close(self) -> None:
            pass

    for frame in (
        b"\x82\x00",  # binary data frame
        b"\x01\x01x",  # non-final text fragment
        b"\x81\x7e" + struct.pack(">H", 65535),  # oversized declared payload
    ):
        ws = object.__new__(_WebSocket)
        ws._sock = Socket(frame)
        ws._buffer = b""
        with pytest.raises(BrowserUnavailable):
            ws.recv()


def test_authentik_identification_expression_rolls_back_on_late_failure() -> None:
    from cloudbrowser.browser_slots.page_actions import _authentik_identification_expression

    expression = _authentik_identification_expression(
        expected_origins=("https://auth.example.test",),
        username_selector="input[name=uidField]",
        password_selector="input[name=password]",
        submit_selector="button[type=submit]",
        rejected_selector="[role=alert]",
        username="alice",
        password="secret",
    )
    assert "transaction_failed" in expression
    assert "restore" in expression
    assert "try" in expression


def test_process_rebind_rejects_empty_or_unbounded_secondary_binding(tmp_path) -> None:
    from cloudbrowser.browser_slots.browser_process import BrowserProcess, BrowserProcessConfig

    process = BrowserProcess(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="owner-a",
            generation="generation-a",
        )
    )
    with pytest.raises(ValueError):
        process.rebind("owner-b", "generation-b", profile_id="")
    with pytest.raises(ValueError):
        process.rebind("owner-b", "generation-b", browser_id="x" * 257)


def test_deadline_policy_requires_ttl_outer_and_stage_order() -> None:
    from cloudbrowser.security.policy import validate_deadline_policy

    validate_deadline_policy(ttl_s=31, outer_timeout_s=30, stage_timeout_s=20)
    with pytest.raises(ValueError):
        validate_deadline_policy(ttl_s=30, outer_timeout_s=30, stage_timeout_s=20)
    with pytest.raises(ValueError):
        validate_deadline_policy(ttl_s=31, outer_timeout_s=30, stage_timeout_s=29.5)


def test_identity_comparison_is_strict_ascii_email_canonicalization() -> None:
    from cloudbrowser.security.policy import canonical_identity

    assert canonical_identity(" Alice@EXAMPLE.TEST ") == "alice@example.test"
    assert canonical_identity("alice+tag@example.test") == "alice+tag@example.test"
    assert canonical_identity("alice＠example.test") is None
    assert canonical_identity("alice@example") is None
    assert canonical_identity("alice@example.test\n") is None
