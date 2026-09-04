"""Phase 3 authenticated employee journey over real HTTP (TinyAuth fixture).

The gateway must accept a validated TinyAuth session that the trusted edge
injects into the WSGI environ (never from a client header), then serve the
owner-bound listing and attachment over real HTTP.

The internal downloads dependency is a real local HTTP stub so the journey
exercises the typed HTTP client, not the in-process adapter.
"""

from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


class _DownloadsStub:
    """Minimal internal downloads/v1 stub keyed by X-CB-Principal."""

    def __init__(self) -> None:
        self.files = {
            "owner-a": {"invoice.pdf": b"%PDF-1.4 owner-a"},
            "owner-b": {"secret.pdf": b"%PDF-1.4 owner-b"},
        }

    def handler(self):
        files = self.files

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, code, body, content_type="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                principal = self.headers.get("X-CB-Principal", "")
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    self._send(200, b'{"status":"ok"}')
                    return
                if path == "/api/files":
                    entries = [
                        {"name": name, "size": len(body), "mtime": 1}
                        for name, body in files.get(principal, {}).items()
                    ]
                    payload = json.dumps({"entries": entries}).encode("utf-8")
                    self._send(200, payload)
                    return
                if path.startswith("/file/"):
                    name = path[len("/file/") :]
                    body = files.get(principal, {}).get(name)
                    if body is None:
                        self._send(404, b'{"error_code":"not_found"}')
                        return
                    self._send(200, body, content_type="application/octet-stream")
                    return
                self._send(404, b'{"error_code":"not_found"}')

        return Handler

    def start(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread


def _tinyauth_fixture(app, session):
    """Trusted edge fixture: inject a validated session into the environ.

    This mirrors the production TinyAuth middleware that authenticates the
    request and passes the server-validated session to the gateway. The
    session key is a non-HTTP environ entry, so a public client can never
    forge it (WSGI maps only HTTP_* keys from request headers).
    """

    from cloudbrowser.cloudfiles.api import SESSION_ENVIRON_KEY

    def middleware(environ, start_response):
        environ[SESSION_ENVIRON_KEY] = session
        return app(environ, start_response)

    return middleware


def _gateway_app(downloads_base_url: str):
    from cloudbrowser.cloudfiles.runtime import build_app

    return build_app(
        downloads_base_url=downloads_base_url,
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
    )


def _session(subject: str):
    from cloudbrowser.cloudfiles.identity import TinyAuthSession

    return TinyAuthSession(
        subject=subject,
        request_id="req-journey-1",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-1",
    )


def test_employee_journey_over_http_lists_only_owner_files_and_downloads_attachment():
    downloads, downloads_thread = _DownloadsStub().start()
    gateway = _gateway_app(
        downloads_base_url=f"http://127.0.0.1:{downloads.server_address[1]}"
    )
    app = _tinyauth_fixture(gateway, _session("owner-a"))
    server, thread = _serve(app)
    try:
        # Forged owner headers must not change the server-bound principal.
        forged = {
            "X-CB-Principal": "owner-b",
            "Remote-Email": "owner-b@example.test",
            "Accept": "application/json",
        }
        status, headers, body = _request(server, "/api/files", forged)
        assert status == 200, body
        assert headers["Content-Type"].startswith("application/json")
        entries = json.loads(body)["entries"]
        assert [entry["name"] for entry in entries] == ["invoice.pdf"], entries

        status, headers, body = _request(server, "/file/invoice.pdf", forged)
        assert status == 200, body
        assert headers["Content-Disposition"].startswith("attachment")
        assert body == b"%PDF-1.4 owner-a"

        status, _, body = _request(
            server, "/file/invoice.pdf", {"X-CB-Principal": "owner-a"}
        )
        assert status == 200
        assert b"%PDF-1.4 owner-a" in body
        assert b"owner-b" not in body
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        downloads.shutdown()
        downloads_thread.join(timeout=3)
        downloads.server_close()


def test_owner_b_cannot_read_owner_a_file_over_http():
    downloads, downloads_thread = _DownloadsStub().start()
    gateway = _gateway_app(
        downloads_base_url=f"http://127.0.0.1:{downloads.server_address[1]}"
    )
    app = _tinyauth_fixture(gateway, _session("owner-b"))
    server, thread = _serve(app)
    try:
        status, _, body = _request(server, "/file/invoice.pdf")
        assert status == 404, (status, body)
        status, _, body = _request(server, "/api/files")
        entries = json.loads(body)["entries"]
        assert [entry["name"] for entry in entries] == ["secret.pdf"]
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        downloads.shutdown()
        downloads_thread.join(timeout=3)
        downloads.server_close()


def test_html_listing_is_escaped_and_served_only_to_authenticated_sessions():
    downloads, downloads_thread = _DownloadsStub().start()
    gateway = _gateway_app(
        downloads_base_url=f"http://127.0.0.1:{downloads.server_address[1]}"
    )
    app = _tinyauth_fixture(gateway, _session("owner-a"))
    server, thread = _serve(app)
    try:
        status, headers, body = _request(
            server, "/", {"Accept": "text/html"}
        )
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b"invoice.pdf" in body
        assert b"owner-a@" not in body

        # The same route without an authenticated session fails closed.
        bare = _gateway_app(
            downloads_base_url=f"http://127.0.0.1:{downloads.server_address[1]}"
        )
        bare_server, bare_thread = _serve(bare)
        try:
            status, _, body = _request(bare_server, "/", {"Accept": "text/html"})
            assert status == 401, (status, body)
        finally:
            bare_server.shutdown()
            bare_thread.join(timeout=3)
            bare_server.server_close()
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        downloads.shutdown()
        downloads_thread.join(timeout=3)
        downloads.server_close()
