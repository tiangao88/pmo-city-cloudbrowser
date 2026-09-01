import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from cloudbrowser.browser_slots.http_client import HttpJsonClient
from cloudbrowser.browser_slots.transport import BrowserUnavailable


class RecordingHandler(BaseHTTPRequestHandler):
    last_request: tuple[str, str, bytes] | None = None
    response_body = b'{"ok":true}'
    response_type = "application/json"

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).last_request = (self.command, self.path, body)
        self.send_response(200)
        self.send_header("Content-Type", self.response_type)
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: object) -> None:
        return


def server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    value = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    return value, thread


def test_http_json_client_sends_only_relative_json_api_requests():
    value, thread = server()
    try:
        client = HttpJsonClient(f"http://127.0.0.1:{value.server_address[1]}", timeout_s=2)
        assert client.request("POST", "/browser/pages/open", body="https://example.test/a") == {
            "ok": True
        }
        assert RecordingHandler.last_request == (
            "POST",
            "/browser/pages/open",
            b"https://example.test/a",
        )
    finally:
        value.shutdown()
        thread.join(timeout=2)
        value.server_close()


def test_http_json_client_rejects_unsafe_base_urls_and_paths():
    with pytest.raises(ValueError):
        HttpJsonClient("file:///tmp/browser")
    with pytest.raises(ValueError):
        HttpJsonClient("http://user:pass@example.test")
    client = HttpJsonClient("http://example.test")
    with pytest.raises(ValueError):
        client.request("GET", "https://other.test/browser")
    with pytest.raises(ValueError):
        client.request("GET", "/browser/../secrets")


def test_http_json_client_rejects_non_json_responses():
    value, thread = server()
    RecordingHandler.response_body = b"not-json"
    RecordingHandler.response_type = "text/plain"
    try:
        client = HttpJsonClient(f"http://127.0.0.1:{value.server_address[1]}", timeout_s=2)
        with pytest.raises(BrowserUnavailable):
            client.request("POST", "/browser/start")
    finally:
        RecordingHandler.response_body = b'{"ok":true}'
        RecordingHandler.response_type = "application/json"
        value.shutdown()
        thread.join(timeout=2)
        value.server_close()
