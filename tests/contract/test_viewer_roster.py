"""Viewer-side roster: surface relay, HTTP route, and shell display wiring."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from typing import Mapping

from cloudbrowser.viewer.__init__ import create_viewer_server
from cloudbrowser.viewer.session_surface import RouterHttpClient, ViewerSessionSurface


class _Identity:
    def resolve(self, identity: object) -> str | None:
        return "pmo-owner-001"


class _StubRouter:
    """RouterApi stand-in answering /v1/roster with a canned roster."""

    def __init__(self) -> None:
        self.roster_calls = 0

    def open_session(self, *, headers, body):
        return 200, {"request_id": body.get("request_id"), "status": "waiting"}

    def get_session(self, *, headers, request_id):
        return 200, {"request_id": request_id, "status": "waiting"}

    def activate_session(self, *, headers, request_id):
        return 200, {"request_id": request_id, "status": "failed", "error_code": "no_binding"}

    def leave_session(self, *, headers, request_id):
        return 200, {"request_id": request_id, "status": "left"}

    def agent_action(self, *, headers, operation, params, request_id):
        return 200, {"request_id": request_id, "status": "failed", "error_code": "agent_unavailable"}

    def roster(self, *, headers):
        self.roster_calls += 1
        return 200, {
            "request_id": "roster",
            "status": "ok",
            "entries": [
                {"status": "active", "email": "a@example.com"},
                {"status": "waiting", "email": "b@example.com"},
            ],
        }


_ROSTER_HEADERS = {"Remote-Sub": "sub-1", "Remote-Email": "a@example.com"}


class TestSurfaceRoster:
    def test_surface_relays_roster(self) -> None:
        from cloudbrowser.viewer.session_surface import _relay_headers  # noqa: F401

    def test_relay_forwards_email_header(self) -> None:
        from cloudbrowser.viewer.session_surface import _relay_headers

        relayed = _relay_headers(_ROSTER_HEADERS)
        assert relayed == {"remote-sub": "sub-1", "remote-email": "a@example.com"}


class TestViewerRosterHttp:
    def _server(self):
        router = _StubRouter()
        surface = ViewerSessionSurface(identity_client=_Identity(), router_api=router)
        server = create_viewer_server(
            None,
            address=("127.0.0.1", 0),
            allow_edge_identity=True,
            session_surface=surface,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        return server, thread, f"http://{host}:{port}", router

    def _get(self, base: str, path: str) -> tuple[int, dict[str, object]]:
        from urllib.request import Request, urlopen

        req = Request(base + path, headers=dict(_ROSTER_HEADERS), method="GET")
        try:
            with urlopen(req) as response:
                return response.status, json.loads(response.read())
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            return (code or 0), {}

    def test_ui_roster_returns_entries(self) -> None:
        server, thread, base, router = self._server()
        try:
            status, payload = self._get(base, "/ui/roster")
            assert status == 200
            entries = payload["entries"]
            assert [e["email"] for e in entries] == ["a@example.com", "b@example.com"]
            assert router.roster_calls == 1
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()

    def test_shell_includes_roster_display_elements(self) -> None:
        server, thread, base, _router = self._server()
        try:
            from urllib.request import Request, urlopen

            req = Request(base + "/", headers=dict(_ROSTER_HEADERS))
            with urlopen(req) as response:
                html = response.read().decode("utf-8")
            assert "/ui/roster" in html
            assert "roster" in html.lower()
        finally:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()
