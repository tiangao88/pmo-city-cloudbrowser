"""Browser process HTTP service with owner-bound readiness metadata."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from .browser_process import BrowserProcess
from .chrome_adapter import ChromeBrowserAdapter
from .transport import BrowserUnavailable


def create_browser_server(
    adapter: ChromeBrowserAdapter,
    process: BrowserProcess,
    *,
    instance_id: str,
    release_version: str,
    address: tuple[str, int] = ("127.0.0.1", 9230),
) -> ThreadingHTTPServer:
    """Create the restricted browser API consumed by the slot supervisor."""
    if not instance_id or not release_version:
        raise ValueError("instance_id and release_version are required")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path == "/browser/readiness":
                    ready = adapter.readiness()
                    self._send_json(
                        200 if process.readiness() else 503,
                        {
                            "owner": ready.owner,
                            "generation": ready.generation,
                            "cdp_ok": ready.cdp_ok and process.readiness(),
                            "browser_state": process.state,
                        },
                    )
                    return
                if self.path == "/browser/health":
                    self._send_json(
                        200 if process.readiness() else 503,
                        {
                            "status": "ok" if process.readiness() else "degraded",
                            "component": "browser",
                            "instance_id": instance_id,
                            "release_version": release_version,
                            "browser_state": process.state,
                        },
                    )
                    return
                if self.path == "/browser/pages":
                    self._send_json(200, {"urls": adapter.list_page_urls()})
                    return
                self.send_error(404)
            except BrowserUnavailable:
                self._send_json(503, {"ok": False, "error_code": "browser_unavailable"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path == "/browser/start":
                    adapter.start()
                elif self.path == "/browser/stop":
                    adapter.stop()
                elif self.path == "/browser/pages/open":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 4096:
                        raise ValueError("invalid body length")
                    adapter.open_page(self.rfile.read(length).decode("utf-8"))
                elif self.path == "/browser/pages/close-empty":
                    adapter.close_empty_pages()
                else:
                    self.send_error(404)
                    return
                self._send_json(200, {"ok": True})
            except (BrowserUnavailable, ValueError, UnicodeDecodeError):
                self._send_json(503, {"ok": False, "error_code": "browser_operation_failed"})

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer(address, Handler)
