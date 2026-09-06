from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from cloudbrowser.browser_slots import BrowserBinding, OwnerBoundLifecycle, SlotSupervisor
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.router.control_api import ControlApi, ControlRequest, create_control_server


TRUSTED_SECRET = "router-supervisor-secret-012345"


class FakeBrowserClient:
    def request(self, method: str, path: str, *, body: str | None = None) -> object:
        del body
        if method == "POST" and path == "/browser/start":
            return {"ok": True}
        if method == "POST" and path == "/browser/stop":
            return {"ok": True}
        if method == "GET" and path == "/browser/readiness":
            return {"owner": "principal-a", "generation": "g1", "cdp_ok": True}
        if method == "GET" and path == "/browser/pages":
            return {"urls": []}
        if method == "POST" and path == "/browser/pages/close-empty":
            return {"ok": True}
        raise AssertionError((method, path))


def _api(tmp_path):
    binding = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")
    transport = HttpBrowserTransport(
        FakeBrowserClient(), expected_owner="principal-a", expected_generation="g1"
    )
    api = ControlApi(
        SlotSupervisor(OwnerBoundLifecycle(binding, tmp_path / "tabs.json"), transport),
        binding,
        trusted_secret=TRUSTED_SECRET,
    )
    return api


def test_control_api_uses_server_derived_binding_for_wake(tmp_path):
    assert _api(tmp_path).handle(ControlRequest("wake", "req-1")) == {
        "request_id": "req-1",
        "status": "ready",
        "state": "ready",
        "restored_count": 0,
    }


def test_control_api_rejects_unknown_operation_without_browser_call(tmp_path):
    assert _api(tmp_path).handle(ControlRequest("raw-cdp", "req-2")) == {
        "request_id": "req-2",
        "status": "unsupported",
        "error_code": "operation_not_supported",
    }


def test_control_server_returns_bounded_json(tmp_path):
    server = create_control_server(_api(tmp_path), address=("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/control",
            data=json.dumps({"operation": "wake", "request_id": "req-3"}).encode(),
            headers={"Content-Type": "application/json", "X-CB-Trusted-Secret": TRUSTED_SECRET},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.load(response)
        assert payload["status"] == "ready"
        assert "password" not in json.dumps(payload).lower()
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_control_server_rejects_missing_secret_before_parsing_or_dispatch(tmp_path):
    server = create_control_server(_api(tmp_path), address=("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/control",
            data=b"not-json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=2)
        assert exc.value.code == 401
        assert exc.value.read() == b'{"status":"failed","error_code":"unauthorized"}'
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_control_server_rejects_wrong_secret_without_leaking_it(tmp_path):
    server = create_control_server(_api(tmp_path), address=("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    attacker_secret = "attacker-secret-that-must-not-echo"
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/control",
            data=b'{"operation":"wake","request_id":"req-4"}',
            headers={"Content-Type": "application/json", "X-CB-Trusted-Secret": attacker_secret},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=2)
        body = exc.value.read()
        assert exc.value.code == 401
        assert len(body) <= 128
        assert TRUSTED_SECRET.encode() not in body
        assert attacker_secret.encode() not in body
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
