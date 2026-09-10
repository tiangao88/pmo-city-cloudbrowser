"""Real Chrome proof for exact target selection and atomic DOM mutation.

The fixture uses ordinary DOM. It proves CDP target selection and one-evaluate
credential mutation, not Authentik's production closed-shadow implementation.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

import pytest

from cloudbrowser.browser_slots.chrome_adapter import ChromeHttpClient
from cloudbrowser.browser_slots.page_actions import CdpPageActionAdapter
from cloudbrowser.browser_slots.transport import BrowserUnavailable

CHROME = Path("/opt/data/browsers/chromium-1228/chrome-linux64/chrome")


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_json(url: str, timeout_s: float = 5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:
                return json.loads(response.read())
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"Chrome endpoint did not become ready: {url}")


@pytest.mark.skipif(not CHROME.is_file(), reason="real Chrome executable unavailable")
def test_real_chrome_authentik_rejection_probe_reports_clear_and_rejected(tmp_path: Path) -> None:
    class FixtureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = (
                b"<title>rejection fixture</title><main>ready</main>"
                if self.path == "/clear"
                else b"<title>rejection fixture</title><main><div role=alert>no</div></main>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    fixture_origin = f"http://127.0.0.1:{fixture.server_address[1]}"
    port = _port()
    process = subprocess.Popen(
        [
            str(CHROME),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={tmp_path / 'rejection-profile'}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        chrome = ChromeHttpClient(f"http://127.0.0.1:{port}")
        _wait_json(f"http://127.0.0.1:{port}/json/version")
        actions = CdpPageActionAdapter(chrome)
        for path, expected in (("/clear", "clear"), ("/rejected", "rejected")):
            target = chrome.json_request(
                "/json/new?" + quote(fixture_origin + path, safe=""), method="PUT"
            )
            target_id = target["id"]
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    info = actions.broker_page_info(target_id)
                except BrowserUnavailable:
                    time.sleep(0.05)
                    continue
                if info["url"] == fixture_origin + path:
                    break
                time.sleep(0.05)
            assert actions.broker_authentik_rejection(
                target_id,
                expected_origins=(fixture_origin,),
                rejected_selector="main [role=alert]",
            ) == {"state": expected}
    finally:
        process.terminate()
        process.wait(timeout=5)
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=2)


@pytest.mark.skipif(not CHROME.is_file(), reason="real Chrome executable unavailable")
def test_real_cdp_exact_target_atomic_authentik_fixture(tmp_path: Path) -> None:
    class FixtureHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/other":
                body = b"<title>other</title>"
            else:
                body = (
                    b"<title>auth fixture</title><input name=uidField>"
                    b"<input name=password><button type=submit>submit</button>"
                    b"<script>document.querySelector('button').onclick=()=>{"
                    b"document.body.dataset.submitted='yes'}</script>"
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    fixture_origin = f"http://127.0.0.1:{fixture.server_address[1]}"
    port = _port()
    process = subprocess.Popen(
        [
            str(CHROME),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={tmp_path / 'profile'}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "HOME": str(tmp_path)},
    )
    try:
        _wait_json(f"http://127.0.0.1:{port}/json/version")
        chrome = ChromeHttpClient(f"http://127.0.0.1:{port}")
        adapter = CdpPageActionAdapter(chrome)
        first = chrome.json_request("/json/new?" + quote(fixture_origin + "/other", safe=""), method="PUT")
        second = chrome.json_request("/json/new?" + quote(fixture_origin + "/login", safe=""), method="PUT")
        assert isinstance(first, dict) and isinstance(second, dict)
        time.sleep(0.2)
        target_id = second["id"]
        result = adapter.broker_authentik_identification(
            target_id,
            expected_origins=(fixture_origin,),
            username_selector="input[name=uidField]",
            password_selector="input[name=password]",
            submit_selector="button[type=submit]",
            rejected_selector="[role=alert]",
            username="alice",
            password="secret-pw",
        )
        assert result["stage"] == "submitted"
        info = adapter.broker_page_info(target_id)
        assert info["title"] == "auth fixture"
        other = adapter.broker_page_info(first["id"])
        assert other["title"] == "other"
    finally:
        process.terminate()
        process.wait(timeout=5)
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=3)
