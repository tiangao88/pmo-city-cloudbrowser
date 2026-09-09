from __future__ import annotations

import base64
import os
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.browser_slots.basic_auth import BasicAuthCapability
from cloudbrowser.browser_slots.chrome_adapter import ChromeHttpClient
from cloudbrowser.browser_slots.page_actions import _WebSocket
from cloudbrowser.browser_slots.transport import BrowserUnavailable

_CHROME_CANDIDATES = (
    Path("/opt/data/browsers/chromium-1228/chrome-linux64/chrome"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
)


class _Handler(BaseHTTPRequestHandler):
    expected = "Basic " + base64.b64encode(b"alice:secret-pw").decode("ascii")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.headers.get("Authorization") != self.expected:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="CDP test"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"authenticated"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _HttpsServer(ThreadingHTTPServer):
    daemon_threads = True


def _chrome() -> Path | None:
    configured = os.environ.get("CB_TEST_CHROME_EXECUTABLE")
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_file() else None
    return next((path for path in _CHROME_CANDIDATES if path.is_file()), None)


def _certificates(root: Path) -> tuple[Path, Path]:
    cert = root / "cert.pem"
    key = root / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_json(url: str, timeout_s: float = 30.0) -> object:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.2) as response:
                import json

                return json.load(response)
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {url}")


def _new_target(client: ChromeHttpClient, url: str) -> str:
    raw = client.json_request(
        "/json/new?" + urllib.parse.quote(url, safe=""),
        method="PUT",
    )
    assert isinstance(raw, dict)
    target_id = raw.get("id")
    assert isinstance(target_id, str) and target_id
    return target_id


@pytest.mark.skipif(_chrome() is None, reason="real Chromium is unavailable")
def test_basic_auth_capability_fills_real_chrome_cdp_challenge() -> None:
    chrome_binary = _chrome()
    assert chrome_binary is not None
    with tempfile.TemporaryDirectory(prefix="cb-basic-cdp-") as raw_root:
        root = Path(raw_root)
        cert, key = _certificates(root)
        server = _HttpsServer(("127.0.0.1", 0), _Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"https://127.0.0.1:{server.server_port}"

        debug_port = _free_port()
        profile = root / "profile"
        process = subprocess.Popen(
            [
                str(chrome_binary),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--ignore-certificate-errors",
                "--allow-insecure-localhost",
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={debug_port}",
                "--remote-debugging-address=127.0.0.1",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_json(f"http://127.0.0.1:{debug_port}/json/version")
            client = ChromeHttpClient(f"http://127.0.0.1:{debug_port}")
            target_id = _new_target(client, origin + "/protected")
            capability = BasicAuthCapability(
                client,
                ws_factory=lambda url, timeout_s: _WebSocket(
                    url, open_timeout_s=3.0, command_timeout_s=timeout_s
                ),
            )

            state = capability.probe(target_id=target_id)
            assert state["challenge_origin"] == origin
            assert state["application_authenticated"] is False

            capability.submit(
                origin,
                "alice",
                "secret-pw",
                target_id=target_id,
                success_path="/protected",
            )
            state = capability.state(target_id=target_id)
            assert state["challenge_origin"] is None
            assert state["application_authenticated"] is True
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.mark.skipif(_chrome() is None, reason="real Chromium is unavailable")
def test_basic_auth_capability_rejects_wrong_password_via_real_cdp() -> None:
    chrome_binary = _chrome()
    assert chrome_binary is not None
    with tempfile.TemporaryDirectory(prefix="cb-basic-cdp-wrong-") as raw_root:
        root = Path(raw_root)
        cert, key = _certificates(root)
        server = _HttpsServer(("127.0.0.1", 0), _Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"https://127.0.0.1:{server.server_port}"

        debug_port = _free_port()
        process = subprocess.Popen(
            [
                str(chrome_binary),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--ignore-certificate-errors",
                "--allow-insecure-localhost",
                f"--user-data-dir={root / 'profile'}",
                f"--remote-debugging-port={debug_port}",
                "--remote-debugging-address=127.0.0.1",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _wait_json(f"http://127.0.0.1:{debug_port}/json/version")
            client = ChromeHttpClient(f"http://127.0.0.1:{debug_port}")
            target_id = _new_target(client, origin + "/protected")
            capability = BasicAuthCapability(
                client,
                ws_factory=lambda url, timeout_s: _WebSocket(
                    url, open_timeout_s=3.0, command_timeout_s=timeout_s
                ),
            )
            capability.probe(target_id=target_id)
            capability.submit(
                origin,
                "alice",
                "wrong-password",
                target_id=target_id,
                success_path="/protected",
            )
            state = capability.state(target_id=target_id)
            assert state["challenge_origin"] == origin
            assert state["application_authenticated"] is False
        except BrowserUnavailable as exc:
            pytest.fail(f"wrong-password challenge should be reported, not crash: {exc}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
