"""Disposable display feasibility only. No broker, grants or real profiles."""
import json
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

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

# Synthetic fixture secret only; this is not an authentication deployment.
SECRET = "novnc-disposable-fixture-only"


def action(operation, params):
    request = Request(
        "http://127.0.0.1:8090/agent-control/v1",
        data=json.dumps({"request_id": "spike", "operation": operation, "params": params}).encode(),
        headers={"Content-Type": "application/json", "X-CB-Trusted-Secret": SECRET,
                 "X-CB-Principal": "fixture-owner", "X-CB-Browser": "fixture-browser",
                 "X-CB-Generation": "fixture-g1"},
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/task":
            self.send_error(404)
            return
        body = b'''<!doctype html><meta charset="utf-8"><title>CloudBrowser noVNC proof</title>
        <main style="font:24px sans-serif;padding:48px">
        <h1>Same Chromium, two interfaces</h1>
        <p>DISPOSABLE TEST ONLY - no credentials or production access</p>
        <label>Message <input id="message" style="font:inherit" autofocus></label>
        <button id="apply" style="font:inherit" onclick="document.querySelector('output').textContent='Received: '+document.querySelector('input').value">Apply</button>
        <p><output>Waiting for input</output></p></main>'''
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    children, servers = [], []
    browser = None
    with tempfile.TemporaryDirectory(prefix="novnc-fixture-") as temporary:
        try:
            children.append(subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"]))
            for _ in range(100):
                if subprocess.run(["xdpyinfo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("display did not start")
            fixture = ThreadingHTTPServer(("127.0.0.1", 8088), Fixture)
            servers.append(fixture)
            threading.Thread(target=fixture.serve_forever, daemon=True).start()
            chrome = ChromeHttpClient("http://127.0.0.1:9222")
            browser = BrowserProcess(BrowserProcessConfig(
                executable="/usr/bin/chromium", profile_dir=Path(temporary) / "profiles",
                profile_root=Path(temporary) / "profiles", http_port=9222,
                owner="fixture-owner", profile_id="fixture-profile",
                browser_id="fixture-browser", generation="fixture-g1",
                extra_args=("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                            "--disable-background-networking", "--window-size=1280,800"),
            ), probe=lambda: chrome_version_is_ready(chrome.json_request("/json/version")),
                graceful_shutdown=lambda: request_chromium_shutdown(chrome))
            adapter = ChromeBrowserAdapter(chrome, owner="fixture-owner", generation="fixture-g1",
                profile_id="fixture-profile", browser_id="fixture-browser",
                page_actions=CdpPageActionAdapter(chrome))
            backend = create_browser_server(adapter, browser, instance_id="novnc-spike",
                release_version="experiment", address=("127.0.0.1", 9230))
            servers.append(backend)
            threading.Thread(target=backend.serve_forever, daemon=True).start()
            browser.start()
            transport = HttpBrowserTransport(HttpJsonClient("http://127.0.0.1:9230"),
                expected_owner="fixture-owner", expected_generation="fixture-g1")
            agent = build_agent_control_server(transport, principal_id="fixture-owner",
                browser_id="fixture-browser", generation="fixture-g1", shared_secret=SECRET,
                address=("127.0.0.1", 8090))
            servers.append(agent)
            threading.Thread(target=agent.serve_forever, daemon=True).start()
            opened = action("tab_open", {"url": "http://127.0.0.1:8088/task"})
            if opened.get("status") != "ok":
                raise RuntimeError("mediated tab creation failed")
            children.append(subprocess.Popen(["x11vnc", "-display", ":99", "-localhost",
                "-rfbport", "5900", "-forever", "-shared", "-nopw", "-noxdamage", "-nosel"]))
            children.append(subprocess.Popen(["websockify", "--web=/usr/share/novnc",
                "0.0.0.0:6080", "127.0.0.1:5900"]))
            print("Synthetic viewer ready; no SSO, no broker, no takeover enforcement", flush=True)
            while not stop.wait(0.5):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("display service stopped")
        finally:
            if browser is not None:
                browser.stop()
            for server in reversed(servers):
                server.shutdown()
                server.server_close()
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


if __name__ == "__main__":
    main()
