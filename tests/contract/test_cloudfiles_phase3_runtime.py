"""CloudFiles gateway runtime tests."""

from __future__ import annotations

from http.client import HTTPConnection
import json
import threading
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler


def _serve(app):
    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            return

    server = WSGIServer(("127.0.0.1", 0), QuietHandler)
    server.set_app(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _request(server, path, headers=None):
    connection = HTTPConnection(*server.server_address, timeout=3)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def test_downloads_client_readiness_is_a_bounded_health_probe(monkeypatch):
    from cloudbrowser.cloudfiles.downloads_client import DownloadsClient

    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b'{"status":"ok"}'

    def fake_urlopen(request, *, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        return Response()

    monkeypatch.setattr("cloudbrowser.cloudfiles.downloads_client.urlopen", fake_urlopen)
    client = DownloadsClient("http://downloads:8083", "s" * 32)
    assert client.ready is True
    assert calls[0][0] == "http://downloads:8083/health"
    assert calls[0][1]["X-cb-trusted-secret"] == "s" * 32
    assert calls[0][2] == 3.0


def test_runtime_health_is_unauthenticated_and_bounded():
    from cloudbrowser.cloudfiles.runtime import build_app

    app = build_app(
        downloads_base_url="http://downloads:8083",
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
    )
    server, thread = _serve(app)
    try:
        status, headers, body = _request(server, "/health")
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
    payload = json.loads(body)
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert payload == {
        "status": "ok",
        "component": "cloudfiles",
        "instance": "cloudfil",
    }


def test_runtime_fails_closed_without_session_and_does_not_echo_forged_identity():
    from cloudbrowser.cloudfiles.runtime import build_app

    app = build_app(
        downloads_base_url="http://downloads:8083",
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
    )
    server, thread = _serve(app)
    try:
        status, _, body = _request(
            server,
            "/api/files",
            {"Remote-Email": "victim@example.test", "X-CB-Principal": "victim"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
    assert status == 401
    assert b"victim@example.test" not in body
    assert b"victim" not in body
