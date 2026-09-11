"""Browser-side action gate closes the agent-control handoff race."""
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cloudbrowser.browser_slots import BrowserBinding, BrowserReadiness
from cloudbrowser.browser_slots.browser_server import create_browser_server


def test_browser_sidecar_refuses_stale_agent_action_before_side_effect():
    class Adapter:
        binding = BrowserBinding("profile-bob", "bob", "slot-1", "g2")
        chrome = None
        calls = []

        def readiness(self): return BrowserReadiness("bob", "g2", True)
        def open_page(self, url):
            self.calls.append(url)
            return {"tab_id": "BOB", "url": url, "title": "untitled"}

    class Process:
        state = "ready"
        def readiness(self): return True
        def stop(self): pass

    adapter = Adapter()
    server = create_browser_server(
        adapter, Process(), instance_id="test", release_version="test",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"url": "https://example.test"}).encode()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/agent/pages/open",
            data=body, method="POST", headers={
                "X-CB-Principal": "alice", "X-CB-Generation": "g1",
                "Content-Type": "application/json",
            },
        )
        try:
            urlopen(request, timeout=2)
        except HTTPError as response:
            assert response.code == 503
            assert json.load(response) == {"ok": False, "error_code": "browser_operation_failed"}
        else:
            raise AssertionError("stale agent binding was accepted")
        assert adapter.calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
