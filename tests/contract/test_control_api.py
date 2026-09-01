from cloudbrowser.browser_slots import BrowserBinding, OwnerBoundLifecycle, SlotSupervisor
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.router.control_api import ControlApi, ControlRequest, create_control_server


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


def test_control_api_uses_server_derived_binding_for_wake(tmp_path):
    binding = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")
    transport = HttpBrowserTransport(
        FakeBrowserClient(), expected_owner="principal-a", expected_generation="g1"
    )
    lifecycle = OwnerBoundLifecycle(binding, tmp_path / "tabs.json")
    api = ControlApi(SlotSupervisor(lifecycle, transport), binding)

    assert api.handle(ControlRequest("wake", "req-1")) == {
        "request_id": "req-1",
        "status": "ready",
        "state": "ready",
        "restored_count": 0,
    }


def test_control_api_rejects_unknown_operation_without_browser_call(tmp_path):
    binding = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")
    transport = HttpBrowserTransport(
        FakeBrowserClient(), expected_owner="principal-a", expected_generation="g1"
    )
    api = ControlApi(SlotSupervisor(OwnerBoundLifecycle(binding, tmp_path / "tabs.json"), transport), binding)
    assert api.handle(ControlRequest("raw-cdp", "req-2")) == {
        "request_id": "req-2",
        "status": "unsupported",
        "error_code": "operation_not_supported",
    }


def test_control_server_returns_bounded_json(tmp_path):
    binding = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")
    transport = HttpBrowserTransport(
        FakeBrowserClient(), expected_owner="principal-a", expected_generation="g1"
    )
    api = ControlApi(SlotSupervisor(OwnerBoundLifecycle(binding, tmp_path / "tabs.json"), transport), binding)
    server = create_control_server(api, address=("127.0.0.1", 0))
    import threading
    import urllib.request
    import json

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/control",
            data=json.dumps({"operation": "wake", "request_id": "req-3"}).encode(),
            headers={"Content-Type": "application/json"},
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
