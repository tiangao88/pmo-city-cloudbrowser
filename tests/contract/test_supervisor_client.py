"""HTTP/JSON client contract for the router → slot-supervisor boundary.

The supervisor exposes ``POST /control`` via ``create_control_server``. The
router-side ``SupervisorClient`` must speak that bounded JSON protocol over a
stdlib HTTP transport, with a configurable slot → base URL map. It must
never leak raw exceptions, secrets, principal IDs, or page values.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cloudbrowser.router.supervisor_client import (
    SupervisorClient,
    SupervisorClientError,
    SupervisorUnavailable,
)


TRUSTED_SECRET = "router-supervisor-secret-012345"


class _RecordingHandler(BaseHTTPRequestHandler):
    records: list[tuple[str, str, bytes]] = []
    received_headers: list[dict[str, str]] = []
    reply_status: int = 200
    reply_body: bytes = b'{"request_id":"req-1","status":"ready","state":"ready","restored_count":0}'

    def log_message(self, format, *args) -> None:  # noqa: A002 - stdlib HTTP handler contract
        return

    def do_POST(self):  # noqa: N802 - stdlib HTTP handler contract
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        _RecordingHandler.records.append((self.command, self.path, body))
        _RecordingHandler.received_headers.append(dict(self.headers.items()))
        self.send_response(_RecordingHandler.reply_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_RecordingHandler.reply_body)))
        self.end_headers()
        self.wfile.write(_RecordingHandler.reply_body)


def _serve(*, status: int = 200, body: bytes | None = None) -> ThreadingHTTPServer:
    _RecordingHandler.records = []
    _RecordingHandler.received_headers = []
    _RecordingHandler.reply_status = status
    _RecordingHandler.reply_body = body if body is not None else (
        b'{"request_id":"req-1","status":"ready","state":"ready","restored_count":0}'
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._test_thread = thread  # type: ignore[attr-defined]
    return server


def _close(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server._test_thread.join(timeout=3)  # type: ignore[attr-defined]
    server.server_close()


def _client(server: ThreadingHTTPServer) -> SupervisorClient:
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return SupervisorClient(
        slot_url_map={"slot-1": f"{base}/api", "slot-2": f"{base}/api"},
        trusted_secret=TRUSTED_SECRET,
        timeout_s=2.0,
    )


def test_post_control_sends_bounded_request_to_mapped_slot():
    server = _serve()
    try:
        client = _client(server)
        result = client.post_control("slot-1", operation="wake", request_id="req-1")
        assert result == {
            "request_id": "req-1",
            "status": "ready",
            "state": "ready",
            "restored_count": 0,
        }
        assert len(_RecordingHandler.records) == 1
        method, path, body = _RecordingHandler.records[0]
        assert method == "POST"
        assert path == "/api/control"
        payload = json.loads(body)
        assert payload == {"operation": "wake", "request_id": "req-1"}
        assert _RecordingHandler.received_headers[0]["X-Cb-Trusted-Secret"] == TRUSTED_SECRET
    finally:
        _close(server)


def test_post_control_routes_to_configured_slot_url():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        client = SupervisorClient(
            slot_url_map={
                "slot-1": f"{base}/slot1",
                "slot-2": f"{base}/slot2",
            },
            trusted_secret=TRUSTED_SECRET,
            timeout_s=2.0,
        )
        client.post_control("slot-2", operation="suspend", request_id="req-2")
        assert _RecordingHandler.records[0][1] == "/slot2/control"
    finally:
        _close(server)


def test_post_control_unknown_slot_raises_without_http_call():
    server = _serve()
    try:
        client = _client(server)
        with pytest.raises(SupervisorClientError):
            client.post_control("slot-missing", operation="wake", request_id="req")
        assert _RecordingHandler.records == []
    finally:
        _close(server)


def test_post_control_rejects_unknown_operation_locally():
    server = _serve()
    try:
        client = _client(server)
        with pytest.raises(SupervisorClientError):
            client.post_control("slot-1", operation="raw-cdp", request_id="req")
        assert _RecordingHandler.records == []
    finally:
        _close(server)


def test_post_control_http_failure_raises_unavailable():
    server = _serve(
        status=500,
        body=b'{"request_id":"req","status":"failed","error_code":"operation_failed"}',
    )
    try:
        client = _client(server)
        with pytest.raises(SupervisorUnavailable):
            client.post_control("slot-1", operation="wake", request_id="req")
    finally:
        _close(server)


def test_post_control_malformed_response_raises_unavailable():
    server = _serve(body=b"not-json")
    try:
        client = _client(server)
        with pytest.raises(SupervisorUnavailable):
            client.post_control("slot-1", operation="wake", request_id="req")
    finally:
        _close(server)


def test_post_control_invalid_request_id_raises_locally():
    server = _serve()
    try:
        client = _client(server)
        with pytest.raises(SupervisorClientError):
            client.post_control("slot-1", operation="wake", request_id="")
        with pytest.raises(SupervisorClientError):
            client.post_control("slot-1", operation="wake", request_id="x" * 200)
        assert _RecordingHandler.records == []
    finally:
        _close(server)


def test_post_control_invalid_slot_id_raises_locally():
    server = _serve()
    try:
        client = _client(server)
        with pytest.raises(SupervisorClientError):
            client.post_control("", operation="wake", request_id="req")
        with pytest.raises(SupervisorClientError):
            client.post_control("x" * 200, operation="wake", request_id="req")
    finally:
        _close(server)


def test_constructor_rejects_non_http_origin():
    with pytest.raises(ValueError):
        SupervisorClient(
            slot_url_map={"slot-1": "http://user:pw@host:8080/"},
            trusted_secret=TRUSTED_SECRET,
            timeout_s=1.0,
        )
    with pytest.raises(ValueError):
        SupervisorClient(slot_url_map={"slot-1": "ftp://host/"}, trusted_secret=TRUSTED_SECRET, timeout_s=1.0)
    with pytest.raises(ValueError):
        SupervisorClient(
            slot_url_map={"slot-1": "http://host/api?token=x"},
            trusted_secret=TRUSTED_SECRET,
            timeout_s=1.0,
        )
    with pytest.raises(ValueError):
        SupervisorClient(
            slot_url_map={"slot-1": "http://host/api/../escape"},
            trusted_secret=TRUSTED_SECRET,
            timeout_s=1.0,
        )
    # A simple absolute path prefix is allowed.
    SupervisorClient(slot_url_map={"slot-1": "http://host/api"}, trusted_secret=TRUSTED_SECRET, timeout_s=1.0)


def test_constructor_rejects_invalid_timeout():
    with pytest.raises(ValueError):
        SupervisorClient(slot_url_map={"slot-1": "http://host"}, trusted_secret=TRUSTED_SECRET, timeout_s=0.0)
    with pytest.raises(ValueError):
        SupervisorClient(slot_url_map={"slot-1": "http://host"}, trusted_secret=TRUSTED_SECRET, timeout_s=31.0)


@pytest.mark.parametrize("secret", ["", "short", None, b"bytes-not-supported"])
def test_constructor_rejects_missing_or_short_trusted_secret(secret):
    with pytest.raises(ValueError):
        SupervisorClient(slot_url_map={"slot-1": "http://host"}, trusted_secret=secret, timeout_s=1.0)
