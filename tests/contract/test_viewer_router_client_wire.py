"""Wire-level contract for ViewerSessionSurface over the real RouterHttpClient.

The session surface relays three session routes plus the allowlisted agent
routes to the router control plane. Unit tests elsewhere use fake router
clients; this module verifies the REAL RouterHttpClient against a local
stdlib HTTP server so the actual path, method, headers, and request body
that the router receives are pinned — exactly the layer a fake can mask.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping

from cloudbrowser.viewer.session_surface import RouterHttpClient, ViewerSessionSurface


class _StubRouter:
    """Tiny stdlib router stub recording one request and answering by path."""

    def __init__(self) -> None:
        self.captured: dict[str, object] = {}

    def serve_forever(self) -> None:  # pragma: no cover - stdlib contract
        self._server.serve_forever()

    def start(self) -> str:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self.port}"

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _capture(self, method: str) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                stub.captured = {
                    "method": method,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": json.loads(body) if body else None,
                }
                payload = json.dumps(
                    {"request_id": "req-1", "status": "ok"}
                ).encode()
                self.send_response(200 if "/agent/" not in self.path else 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802 - stdlib contract
                self._capture("POST")

            def do_GET(self) -> None:  # noqa: N802 - stdlib contract
                self._capture("GET")

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=3)
        self._server.server_close()


class _Identity:
    def __init__(self, principal: str = "pmo-owner-001") -> None:
        self._principal = principal

    def resolve(self, identity: object) -> str | None:
        return self._principal


class TestRealRouterClientWire:
    def test_agent_action_posts_bounded_body_to_agent_path(self) -> None:
        stub = _StubRouter()
        base = stub.start()
        try:
            surface = ViewerSessionSurface(
                identity_client=_Identity(),
                router_api=RouterHttpClient(base_url=base),
            )
            status, payload = surface.agent(
                "navigate",
                headers={"Remote-Sub": "sub-1", "Remote-Groups": "PMOC_Users"},
                params={"target_tab_id": "tab-1", "url": "https://example.com/"},
                request_id="ui-r1",
            )
            assert status == 200
            assert payload["status"] == "ok"
            captured = stub.captured
            assert captured["method"] == "POST"
            assert captured["path"] == "/v1/agent/navigate"
            body = captured["body"]
            assert body["request_id"] == "ui-r1"
            assert body["params"] == {"target_tab_id": "tab-1", "url": "https://example.com/"}
            # Only allowlisted identity headers are forwarded.
            sent = captured["headers"]
            assert sent.get("remote-sub") == "sub-1"
            assert sent.get("remote-groups") == "PMOC_Users"
            assert "authorization" not in sent
            assert "cookie" not in sent
        finally:
            stub.stop()

    def test_agent_action_keeps_operation_in_path_allowlisted(self) -> None:
        stub = _StubRouter()
        base = stub.start()
        try:
            surface = ViewerSessionSurface(
                identity_client=_Identity(),
                router_api=RouterHttpClient(base_url=base),
            )
            for op in ("page_info", "tabs_list", "click", "type"):
                status, payload = surface.agent(
                    op,
                    headers={"Remote-Sub": "sub-1"},
                    params={"target_tab_id": "tab-1"} if op == "page_info" else ({} if op == "tabs_list" else {"target_tab_id": "tab-1", "selector": "#q"}),
                    request_id="ui-r1",
                )
                assert status == 200
                assert stub.captured["path"] == f"/v1/agent/{op}"
        finally:
            stub.stop()

    def test_session_routes_keep_wire_shape(self) -> None:
        stub = _StubRouter()
        base = stub.start()
        try:
            surface = ViewerSessionSurface(
                identity_client=_Identity(),
                router_api=RouterHttpClient(base_url=base),
            )
            surface.join(
                headers={"Remote-Sub": "sub-1"},
                request_id="ui-r1",
            )
            assert stub.captured["method"] == "POST"
            assert stub.captured["path"] == "/v1/session"
            assert stub.captured["body"] == {"request_id": "ui-r1"}
            surface.status(
                headers={"Remote-Sub": "sub-1"},
                request_id="ui-r1",
            )
            assert stub.captured["method"] == "GET"
            assert stub.captured["path"] == "/v1/session"
            surface.activate(
                headers={"Remote-Sub": "sub-1"},
                request_id="ui-r1",
            )
            assert stub.captured["path"] == "/v1/session/activate"
            surface.leave(
                headers={"Remote-Sub": "sub-1"},
                request_id="ui-r1",
            )
            assert stub.captured["method"] == "POST"
            assert stub.captured["path"] == "/v1/session/leave"
            assert stub.captured["body"] == {"request_id": "ui-r1"}
        finally:
            stub.stop()