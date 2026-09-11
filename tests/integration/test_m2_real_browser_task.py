"""Real-Chromium M2 task through browser and agent-control HTTP boundaries."""
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.agent_control_service import build_agent_control_server
from cloudbrowser.browser_slots.browser_process import (
    BrowserProcess, BrowserProcessConfig, chrome_version_is_ready,
    request_chromium_shutdown,
)
from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter, ChromeHttpClient
from cloudbrowser.browser_slots.http_client import HttpJsonClient
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter

CHROME = Path(os.environ.get("CB_TEST_CHROME_EXECUTABLE", "/opt/data/browsers/chromium-1228/chrome-linux64/chrome"))
SECRET = "m2-router-agent-test-secret"


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _post(origin, operation, request_id, params):
    body = json.dumps({"request_id": request_id, "operation": operation, "params": params}).encode()
    request = Request(
        origin + "/agent-control/v1", data=body, method="POST",
        headers={
            "Content-Type": "application/json", "X-CB-Trusted-Secret": SECRET,
            "X-CB-Principal": "alice", "X-CB-Browser": "slot-1",
            "X-CB-Generation": "g1",
        },
    )
    with urlopen(request, timeout=5) as response:
        return json.load(response)


@pytest.mark.skipif(not CHROME.is_file(), reason="real Chromium is unavailable")
def test_fresh_browser_opens_exact_tab_types_clicks_and_reads_result(tmp_path):
    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"""<!doctype html><title>Synthetic task</title>
            <main><label>Task <input id=task></label>
            <button id=complete onclick=\"document.querySelector('output').textContent='Completed '+document.querySelector('#task').value\">Complete</button>
            <output>Pending</output></main>"""
            if self.path == "/large":
                body = ("<!doctype html><meta charset=utf-8><title>Large page</title><main>" + "🌍 café " * 1500 + "</main>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    task_url = f"http://127.0.0.1:{fixture.server_port}/task"
    debug_port = _free_port()
    chrome = ChromeHttpClient(f"http://127.0.0.1:{debug_port}")
    process = BrowserProcess(
        BrowserProcessConfig(
            executable=str(CHROME), profile_dir=tmp_path / "profiles",
            profile_root=tmp_path / "profiles", http_port=debug_port,
            owner="alice", profile_id="profile-alice", browser_id="slot-1",
            generation="g1", extra_args=(
                "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
            ),
        ),
        probe=lambda: chrome_version_is_ready(chrome.json_request("/json/version")),
        graceful_shutdown=lambda: request_chromium_shutdown(chrome),
    )
    adapter = ChromeBrowserAdapter(
        chrome, owner="alice", generation="g1", profile_id="profile-alice",
        browser_id="slot-1", page_actions=CdpPageActionAdapter(chrome),
    )
    browser_server = create_browser_server(
        adapter, process, instance_id="m2-test", release_version="m2-test",
        address=("127.0.0.1", 0),
    )
    browser_thread = threading.Thread(target=browser_server.serve_forever, daemon=True)
    browser_thread.start()
    agent_server = None
    agent_thread = None
    try:
        process.start()
        transport = HttpBrowserTransport(
            HttpJsonClient(f"http://127.0.0.1:{browser_server.server_port}"),
            expected_owner="alice", expected_generation="g1",
        )
        agent_server = build_agent_control_server(
            transport, principal_id="alice", browser_id="slot-1", generation="g1",
            shared_secret=SECRET, address=("127.0.0.1", 0),
        )
        agent_thread = threading.Thread(target=agent_server.serve_forever, daemon=True)
        agent_thread.start()
        origin = f"http://127.0.0.1:{agent_server.server_port}"

        opened = _post(origin, "tab_open", "req-open", {"url": task_url})
        assert opened["status"] == "ok"
        tab_id = opened["page"]["tab_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = _post(origin, "page_info", "req-ready", {"target_tab_id": tab_id})
            if state.get("status") == "ok" and "Pending" in state["page"]["text"]:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("synthetic task page did not become ready")

        assert _post(origin, "type", "req-type", {
            "target_tab_id": tab_id, "selector": "#task", "text": "Alice",
        })["status"] == "ok"
        assert _post(origin, "click", "req-click", {
            "target_tab_id": tab_id, "selector": "#complete",
        })["status"] == "ok"
        result = _post(origin, "page_info", "req-result", {"target_tab_id": tab_id})
        assert result["status"] == "ok"
        assert "Completed Alice" in result["page"]["text"]
        tabs = _post(origin, "tabs_list", "req-tabs", {})
        assert any(page["tab_id"] == tab_id and page["url"] == task_url for page in tabs["page"])
        stale = _post(origin, "page_info", "req-stale", {"target_tab_id": "stale-tab"})
        assert stale == {"request_id": "req-stale", "status": "failed", "error_code": "browser_unavailable"}
        large = _post(origin, "tab_open", "req-large", {"url": task_url.replace('/task', '/large')})
        assert large["status"] == "ok"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = _post(origin, "page_info", "req-large-read", {"target_tab_id": large["page"]["tab_id"]})
            if result.get("status") == "ok" and result["page"]["title"] == "Large page":
                break
            time.sleep(0.1)
        assert result["status"] == "ok"
        excerpt = result["page"]["text"]
        assert excerpt.startswith("🌍 café ")
        assert excerpt.endswith("[Page text truncated to 4096 UTF-8 bytes]")
        assert len(excerpt.encode()) <= 4096
        assert "\ufffd" not in excerpt
    finally:
        if agent_server is not None:
            agent_server.shutdown()
            agent_server.server_close()
        if agent_thread is not None:
            agent_thread.join(timeout=2)
        browser_server.shutdown()
        browser_server.server_close()
        browser_thread.join(timeout=2)
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=2)
