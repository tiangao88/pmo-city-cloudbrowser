"""Synthetic real-Chromium proof; never uses deployed profiles or accounts."""
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

from cloudbrowser.browser_slots.browser_process import BrowserProcess, BrowserProcessConfig, request_chromium_shutdown
from cloudbrowser.browser_slots.chrome_adapter import ChromeHttpClient
from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter

CHROME = Path(os.environ.get("CB_TEST_CHROME_EXECUTABLE", "/opt/data/browsers/chromium-1228/chrome-linux64/chrome"))


def eventually(check):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("owner continuity condition timed out")


@pytest.mark.skipif(not CHROME.is_file(), reason="real Chromium is unavailable")
def test_real_owner_tabs_cookies_storage_survive_a_b_a_and_second_slot(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/download":
                body = b"synthetic-alice-download"
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="alice.txt"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = b"<title>M1 synthetic fixture</title><main>ready</main>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{fixture.server_port}"
    processes = []

    def launch(owner, slot, generation):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        chrome = ChromeHttpClient(f"http://127.0.0.1:{port}")
        process = BrowserProcess(BrowserProcessConfig(
            executable=str(CHROME), profile_dir=tmp_path / "profiles",
            profile_root=tmp_path / "profiles", download_root=tmp_path / "downloads",
            http_port=port, owner=owner, profile_id="profile-" + owner,
            browser_id=slot, generation=generation,
            extra_args=("--headless=new", "--no-sandbox", "--disable-dev-shm-usage"),
        ), probe=lambda: bool(chrome.json_request("/json/version")), graceful_shutdown=lambda: request_chromium_shutdown(chrome))
        processes.append(process)
        process.start()
        return process, chrome, CdpPageActionAdapter(chrome)

    def target(chrome, path):
        return eventually(lambda: next((t["id"] for t in chrome.json_request("/json/list") if t.get("url") == origin + path), None))

    def evaluate(actions, tab, expression):
        result = actions._agent_command(tab, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
        assert "exceptionDetails" not in result
        return result["result"].get("value")

    try:
        alice, chrome, actions = launch("alice", "slot-1", "g1")
        chrome.json_request("/json/new?" + quote(origin + "/alice", safe=""), method="PUT")
        tab = target(chrome, "/alice")
        eventually(lambda: evaluate(actions, tab, "document.readyState === 'complete'"))
        evaluate(actions, tab, "localStorage.setItem('owner','alice'); document.cookie='owner=alice; Max-Age=3600; Path=/'; true")
        actions._agent_command(tab, "Page.navigate", {"url": origin + "/download"})
        download = alice.config.download_dir / "alice.txt"
        eventually(lambda: download.exists())
        assert download.read_bytes() == b"synthetic-alice-download"
        alice.stop()

        bob, chrome, actions = launch("bob", "slot-1", "g2")
        assert not (bob.config.download_dir / "alice.txt").exists()
        assert not any(t.get("url", "").startswith(origin) for t in chrome.json_request("/json/list"))
        chrome.json_request("/json/new?" + quote(origin + "/bob", safe=""), method="PUT")
        tab = target(chrome, "/bob")
        eventually(lambda: evaluate(actions, tab, "document.readyState === 'complete'"))
        assert evaluate(actions, tab, "[localStorage.getItem('owner'),document.cookie]") == [None, ""]
        evaluate(actions, tab, "localStorage.setItem('owner','bob'); document.cookie='owner=bob; Max-Age=3600; Path=/'; true")
        bob.stop()

        returning, chrome, actions = launch("alice", "slot-2", "g3")
        restored = target(chrome, "/alice")
        eventually(lambda: evaluate(actions, restored, "document.readyState === 'complete'"))
        assert evaluate(actions, restored, "[localStorage.getItem('owner'),document.cookie]") == ["alice", "owner=alice"]
        assert not any(t.get("url") == origin + "/bob" for t in chrome.json_request("/json/list"))
        assert returning.config.profile_dir == alice.config.profile_dir
        assert (returning.config.download_dir / "alice.txt").read_bytes() == b"synthetic-alice-download"
    finally:
        for process in reversed(processes):
            process.stop()
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)
