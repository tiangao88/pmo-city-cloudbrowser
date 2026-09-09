"""HTTP contract for the secret-gated broker-only Basic capability."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from cloudbrowser.browser_slots.browser_server import create_browser_server

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

    def state(self, *, target_id: str):
        return {
            "url": "https://basic.example.test/protected",
            "challenge_origin": "https://basic.example.test",
            "application_authenticated": False,
        }

    def probe(self, *, target_id: str):
        return self.state(target_id=target_id)

    def submit(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
    ) -> None:
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


def test_basic_submit_requires_secret_and_uses_bounded_json() -> None:
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
