"""CloudFiles edge-session bridge security tests."""

from __future__ import annotations

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler

from cloudbrowser.cloudfiles.identity_adapter import edge_session_middleware
from cloudbrowser.identity_links import IdentityLinkClient
from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server

_SECRET = "identity-link-test-secret-012345"
_ISSUER = "https://auth.example.test"
_REALM = "tinyauth.example.test"


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
    def __init__(self) -> None:
        self.files = {
            "pmo-owner-001": {"invoice.pdf": b"%PDF-1.4 owner"},
            "pmo-other-002": {"secret.pdf": b"%PDF-1.4 other"},
        }
        self.observed_principals: list[str] = []

    def handler(self):
        stub = self

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
                stub.observed_principals.append(principal)
                path = self.path.split("?", 1)[0]
                if path == "/health":
                    self._send(200, b'{"status":"ok"}')
                    return
                if path == "/api/files":
                    entries = [
                        {"name": name, "size": len(body), "mtime": 1}
                        for name, body in stub.files.get(principal, {}).items()
                    ]
                    self._send(200, json.dumps({"entries": entries}).encode())
                    return
                self._send(404, b'{"error_code":"not_found"}')

        return Handler

    def start(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread


def _identity_client(tmp_path: Path):
    store = IdentityLinkStore(tmp_path / "identity.sqlite3")
    service = create_identity_link_server(
        store,
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    client = IdentityLinkClient(
        base_url=f"http://127.0.0.1:{service.server_address[1]}",
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
    )
    return service, thread, client


def _close(server, thread):
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def _gateway_app(downloads_base_url: str):
    from cloudbrowser.cloudfiles.runtime import build_app

    return build_app(
        downloads_base_url=downloads_base_url,
        shared_secret="s" * 32,
        instance_id="cloudfiles-test",
        release_version="0.2.0-test",
    )


def test_edge_headers_inject_stable_pmo_session_and_list_owner_files(tmp_path: Path) -> None:
    identity_service, identity_thread, identity_client = _identity_client(tmp_path)
    stub = _DownloadsStub()
    downloads, downloads_thread = stub.start()
    gateway = _gateway_app(f"http://127.0.0.1:{downloads.server_address[1]}")
    app = edge_session_middleware(gateway, identity_client=identity_client)
    server, thread = _serve(app)
    try:
        headers = {
            "Remote-Sub": "oidc-sub-owner",
            "Remote-Email": "owner@example.com",
            "Remote-User": "owner",
            "Remote-Groups": "PMOC_Users",
            "X-CB-Principal": "attacker",
            "X-CB-Owner": "attacker",
            "Accept": "application/json",
        }
        status, _, body = _request(server, "/api/files", headers)
    finally:
        _close(server, thread)
        _close(downloads, downloads_thread)
        _close(identity_service, identity_thread)
    assert status == 200, body
    payload = json.loads(body)
    assert [entry["name"] for entry in payload["entries"]] == []
    assert stub.observed_principals and stub.observed_principals[-1].startswith("pmo-")
    assert stub.observed_principals[-1] != "owner@example.com"


def test_missing_edge_identity_fails_closed(tmp_path: Path) -> None:
    identity_service, identity_thread, identity_client = _identity_client(tmp_path)
    gateway = _gateway_app("http://downloads:8083")
    app = edge_session_middleware(gateway, identity_client=identity_client)
    server, thread = _serve(app)
    try:
        status, _, body = _request(server, "/api/files")
    finally:
        _close(server, thread)
        _close(identity_service, identity_thread)
    assert status == 401
    assert b"downloads:8083" not in body


def test_malformed_edge_identity_fails_closed(tmp_path: Path) -> None:
    identity_service, identity_thread, identity_client = _identity_client(tmp_path)
    gateway = _gateway_app("http://downloads:8083")
    app = edge_session_middleware(gateway, identity_client=identity_client)
    server, thread = _serve(app)
    try:
        status, _, body = _request(server, "/api/files", {"Remote-Email": "a b@example.com"})
    finally:
        _close(server, thread)
        _close(identity_service, identity_thread)
    assert status == 401
    assert b"a b@example.com" not in body


def test_health_remains_unauthenticated_through_middleware(tmp_path: Path) -> None:
    identity_service, identity_thread, identity_client = _identity_client(tmp_path)
    gateway = _gateway_app("http://downloads:8083")
    app = edge_session_middleware(gateway, identity_client=identity_client)
    server, thread = _serve(app)
    try:
        status, _, body = _request(server, "/health")
    finally:
        _close(server, thread)
        _close(identity_service, identity_thread)
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_middleware_injects_session_and_strips_identity_headers(tmp_path: Path) -> None:
    identity_service, identity_thread, identity_client = _identity_client(tmp_path)
    seen = {}

    def recorder(environ, start_response):
        seen["environ"] = dict(environ)
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"ok"]

    app = edge_session_middleware(recorder, identity_client=identity_client)
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/",
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_REMOTE_SUB": "oidc-sub-owner",
        "HTTP_REMOTE_EMAIL": "owner@example.com",
        "HTTP_REMOTE_GROUPS": "PMOC_Users",
        "HTTP_X_CB_OWNER": "attacker",
    }
    statuses = []
    body = b"".join(app(environ, lambda status, headers: statuses.append((status, headers))))
    _close(identity_service, identity_thread)
    assert body == b"ok"
    assert statuses[0][0] == "200 OK"
    assert "HTTP_REMOTE_SUB" not in seen["environ"]
    assert "HTTP_REMOTE_EMAIL" not in seen["environ"]
    assert "HTTP_X_CB_OWNER" not in seen["environ"]
    assert seen["environ"]["cloudbrowser.tinyauth_session"].subject.startswith("pmo-")


def test_local_remote_user_converges_even_when_email_changes(tmp_path: Path) -> None:
    identity_service, identity_thread, identity_client = _identity_client(tmp_path)
    try:
        from cloudbrowser.edge_auth import parse_edge_identity

        first = parse_edge_identity(
            {"Remote-User": "local-owner", "Remote-Email": "pseudo@example.com", "Remote-Groups": "PMOC_Users"}
        )
        second = parse_edge_identity(
            {"Remote-User": "local-owner", "Remote-Email": "another@example.com", "Remote-Groups": "PMOC_Users"}
        )
        assert first is not None and second is not None
        assert identity_client.resolve(first) == identity_client.resolve(second)
    finally:
        _close(identity_service, identity_thread)
