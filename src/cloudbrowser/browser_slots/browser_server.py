"""Browser process API with explicit page action capabilities."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any, Callable
from urllib.parse import urlsplit

from .browser_process import BrowserProcess
from .chrome_adapter import ChromeBrowserAdapter
from .transport import BrowserUnavailable

_MAX_BODY = 8192


def create_browser_server(
    adapter: ChromeBrowserAdapter,
    process: BrowserProcess,
    *,
    instance_id: str,
    release_version: str,
    address: tuple[str, int] = ("127.0.0.1", 9230),
    binding_listener: Callable[[Any], None] | None = None,
) -> ThreadingHTTPServer:
    """Create the restricted browser API consumed by supervisor and agent control.

    ``binding_listener`` (optional) is invoked with the parsed
    ``BrowserBinding`` after a successful trusted-secret-gated binding push;
    the browser service uses it to rotate download attribution to the
    newly adopted identity.
    """
    if not instance_id or not release_version:
        raise ValueError("instance_id and release_version are required")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path in ("/browser/readiness", "/agent/readiness"):
                    ready = adapter.readiness()
                    healthy = process.readiness()
                    self._send_json(
                        200 if healthy else 503,
                        {
                            "owner": ready.owner,
                            "generation": ready.generation,
                            "cdp_ok": ready.cdp_ok and healthy,
                            "browser_state": process.state,
                        },
                    )
                    return
                if self.path == "/browser/health":
                    healthy = process.readiness()
                    state = process.state
                    if state == "stopped":
                        # Boot-stopped mode (CB_BROWSER_AUTOSTART=0): the
                        # container is intentionally Chrome-less until the
                        # slot supervisor adopts a binding and wakes it, so
                        # the deployment healthcheck must pass here.
                        status_code, service_status = 200, "ok"
                    else:
                        status_code = 200 if healthy else 503
                        service_status = "ok" if healthy else "degraded"
                    self._send_json(
                        status_code,
                        {
                            "status": service_status,
                            "component": "browser",
                            "instance_id": instance_id,
                            "release_version": release_version,
                            "browser_state": state,
                        },
                    )
                    return
                if self.path in ("/browser/pages", "/agent/pages"):
                    urls = adapter.list_page_urls()
                    if self.path == "/browser/pages":
                        self._send_json(200, {"urls": urls})
                    else:
                        self._send_json(
                            200,
                            {"pages": [{"tab_id": f"tab-{i}", "url": url, "title": "untitled"} for i, url in enumerate(urls, 1)]},
                        )
                    return
                if urlsplit(self.path).path == "/agent/pages/info":
                    self._send_json(200, adapter.page_info())
                    return
                self.send_error(404)
            except BrowserUnavailable:
                self._send_json(503, {"ok": False, "error_code": "browser_unavailable"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path == "/browser/binding":
                    self._handle_binding_push()
                    return
                if self.path == "/browser/start":
                    adapter.start()
                elif self.path == "/browser/stop":
                    adapter.stop()
                elif self.path == "/browser/pages/open":
                    adapter.open_page(self._read_text())
                elif self.path == "/browser/pages/close-empty":
                    adapter.close_empty_pages()
                elif self.path == "/agent/pages/navigate":
                    adapter.navigate(self._read_text())
                elif self.path == "/agent/pages/click":
                    adapter.click(self._read_text())
                elif self.path == "/agent/pages/type":
                    selector, text = self._read_text().split("\n", 1)
                    adapter.type_text(selector, text)
                else:
                    self.send_error(404)
                    return
                self._send_json(200, {"ok": True})
            except (BrowserUnavailable, ValueError, UnicodeDecodeError):
                self._send_json(503, {"ok": False, "error_code": "browser_operation_failed"})

        def _handle_binding_push(self) -> None:
            """Adopt a server-minted binding (trusted-secret gated).

            Only a stopped browser may be rebound, mirroring the lifecycle
            rule; the adapter and process are rebuilt for the new identity.
            """

            import os

            from cloudbrowser.browser_service import parse_binding_push

            expected = os.environ.get("CB_ROUTER_SHARED_SECRET")
            provided = self.headers.get("X-CB-Trusted-Secret")
            if not expected or not provided:
                self._send_json(403, {"ok": False, "error_code": "binding_not_authorized"})
                return
            try:
                payload = json.loads(self._read_text())
                binding = parse_binding_push(payload, provided_secret=provided)
            except PermissionError:
                # parse_binding_push gates the trusted secret before payload
                # inspection; a mismatch must be a bounded 403, never a dead
                # handler thread.
                self._send_json(403, {"ok": False, "error_code": "binding_not_authorized"})
                return
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error_code": "invalid_binding"})
                return
            if process.state != "stopped":
                self._send_json(409, {"ok": False, "error_code": "browser_not_stopped"})
                return
            process.rebind(binding.principal_id, binding.generation)
            adapter.rebind(binding.principal_id, binding.generation)
            if binding_listener is not None:
                binding_listener(binding)
            self._send_json(200, {"ok": True})

        def _read_text(self) -> str:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid body length") from exc
            if length <= 0 or length > _MAX_BODY:
                raise ValueError("invalid body length")
            return self.rfile.read(length).decode("utf-8")

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer(address, Handler)
