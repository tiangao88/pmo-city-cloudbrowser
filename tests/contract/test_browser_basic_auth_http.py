"""HTTP contract for the secret-gated broker-only Basic capability."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.credential_broker.deadline import BrokerDeadline


class _DeadlineClient:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []
        self.headers: list[dict[str, str]] = []

    def request(self, method, path, *, body=None, headers=None, timeout_s=None):
        self.timeouts.append(timeout_s)
        self.headers.append(dict(headers or {}))
        return {
            "url": "https://basic.example.test/protected",
            "challenge_origin": "https://basic.example.test",
            "application_authenticated": False,
        }


def test_http_basic_uses_remaining_deadline_for_each_request() -> None:
    from cloudbrowser.basic_auth_http import HttpBasicAuthBrowser

    deadline = BrokerDeadline(50.25, monotonic_clock=lambda: 50.0)
    client = _DeadlineClient()
    browser = HttpBasicAuthBrowser(
        client,
        "broker-secret-0123456789abcdef",
        deadline=deadline,
    )

    assert browser.current_url(target_id="target-1") == "https://basic.example.test/protected"
    assert client.timeouts == [pytest.approx(0.25)]
    assert client.headers == [
        {
            "Content-Type": "application/json",
            "X-CB-Broker-Secret": "broker-secret-0123456789abcdef",
            "X-CB-Broker-Deadline-S": "0.250000",
        }
    ]


def test_http_basic_rejects_expired_deadline_before_transport() -> None:
    from cloudbrowser.basic_auth_http import HttpBasicAuthBrowser
    from cloudbrowser.credential_broker.deadline import BrokerDeadlineExceeded

    client = _DeadlineClient()
    browser = HttpBasicAuthBrowser(
        client,
        "broker-secret-0123456789abcdef",
        deadline=BrokerDeadline(50.0, monotonic_clock=lambda: 50.0),
    )

    with pytest.raises(BrokerDeadlineExceeded):
        browser.current_url(target_id="target-1")
    assert client.timeouts == []



SECRET = "broker-secret-0123456789abcdef"


class StubAdapter:
    def list_page_urls(self):
        return ["https://basic.example.test/protected"]


class StubProcess:
    state = "running"

    def readiness(self):
        return True


class StubBasic:
    def __init__(self):
        self.calls: list[tuple[str, str, str, str, str]] = []
        self.deadlines: list[object] = []
        self.raw_state = {
            "url": "https://basic.example.test/protected?code=secret#state",
            "challenge_origin": "https://basic.example.test/?secret=origin#fragment",
            "application_authenticated": False,
        }

    def state(self, *, target_id: str):
        return dict(self.raw_state)

    def probe(self, *, target_id: str, deadline=None):
        self.deadlines.append(deadline)
        return dict(self.raw_state)

    def submit(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
        deadline=None,
    ) -> None:
        self.deadlines.append(deadline)
        self.calls.append((origin, username, password, target_id, success_path))


def _server():
    basic = StubBasic()
    server = create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="test",
        release_version="test",
        address=("127.0.0.1", 0),
        basic_auth=basic,
        broker_submit_secret=SECRET,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, basic


def test_basic_state_requires_broker_secret() -> None:
    server, _ = _server()
    port = server.server_address[1]
    try:
        payload = json.dumps({"target_id": "target-1"}).encode()
        for headers in ({}, {"X-CB-Broker-Secret": "wrong"}):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/broker/basic/state",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json", **headers},
            )
            try:
                urllib.request.urlopen(request, timeout=5)
                raise AssertionError("unauthorized request passed")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/broker/basic/state",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-CB-Broker-Secret": SECRET,
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.loads(response.read()) == {
                "url": "https://basic.example.test/protected",
                "challenge_origin": "https://basic.example.test",
                "application_authenticated": False,
            }
    finally:
        server.shutdown()
        server.server_close()


def test_browser_server_constructs_local_deadline_and_forwards_remaining_timeout() -> None:
    basic = StubBasic()
    server = create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="test",
        release_version="test",
        address=("127.0.0.1", 0),
        basic_auth=basic,
        broker_submit_secret=SECRET,
        monotonic_clock=lambda: 10.0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        payload = json.dumps({"target_id": "target-1"}).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/broker/basic/state",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-CB-Broker-Secret": SECRET,
                "X-CB-Broker-Deadline-S": "0.25",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        assert len(basic.deadlines) == 1
        assert basic.deadlines[0].remaining() == pytest.approx(0.25)
    finally:
        server.shutdown()
        server.server_close()


def test_browser_server_clamps_oversized_deadline_budget() -> None:
    basic = StubBasic()
    server = create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="test",
        release_version="test",
        address=("127.0.0.1", 0),
        basic_auth=basic,
        broker_submit_secret=SECRET,
        monotonic_clock=lambda: 10.0,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/broker/basic/state",
            data=json.dumps({"target_id": "target-1"}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-CB-Broker-Secret": SECRET,
                "X-CB-Broker-Deadline-S": "300",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        assert basic.deadlines[0].remaining() == pytest.approx(30.0)
    finally:
        server.shutdown()
        server.server_close()


    server, basic = _server()
    port = server.server_address[1]
    payload = json.dumps(
        {
            "origin": "https://basic.example.test",
            "username": "alice",
            "password": "pw",
            "target_id": "target-1",
            "success_path": "/home",
        }
    ).encode()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/broker/basic/submit",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("unauthorized request passed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/broker/basic/submit",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "X-CB-Broker-Secret": SECRET},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert json.loads(response.read()) == {"ok": True}
        assert basic.calls == [
            (
                "https://basic.example.test",
                "alice",
                "pw",
                "target-1",
                "/home",
            )
        ]
    finally:
        server.shutdown()
        server.server_close()
