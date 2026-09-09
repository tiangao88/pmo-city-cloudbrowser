"""Browser process API with explicit page action capabilities."""

from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping, Protocol

from .browser_process import BrowserProcess
from .chrome_adapter import ChromeBrowserAdapter
from .transport import BrowserUnavailable

_MAX_BODY = 8192


class BrokerBasicAuthCapability(Protocol):
    def state(self, *, target_id: str) -> dict[str, str | bool | None]: ...

    def probe(self, *, target_id: str) -> dict[str, str | bool | None]: ...

    def submit(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
    ) -> None: ...


def create_browser_server(
    adapter: ChromeBrowserAdapter,
    process: BrowserProcess,
    *,
    instance_id: str,
    release_version: str,
    address: tuple[str, int] = ("127.0.0.1", 9230),
    binding_listener: Callable[[Any], None] | None = None,
    basic_auth: BrokerBasicAuthCapability | None = None,
    broker_submit_secret: str = "",
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
                        pages = [
                            {
                                "tab_id": f"tab-{i}",
                                "url": url,
                                "title": "untitled",
                            }
                            for i, url in enumerate(urls, 1)
                        ]
                        self._send_json(200, {"pages": pages})
                    return
                if self.path == "/broker/basic/state":
                    self.send_error(405)
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
                elif self.path == "/broker/basic/state":
                    if not self._broker_authorized() or basic_auth is None:
                        self._send_json(401, {"ok": False, "error_code": "unauthorized"})
                        return
                    payload = json.loads(self._read_text())
                    if not isinstance(payload, dict):
                        raise ValueError("Basic Auth state payload must be an object")
                    target_id = payload.get("target_id")
                    if not isinstance(target_id, str):
                        raise ValueError("Basic Auth target_id is invalid")
                    probe = getattr(basic_auth, "probe", None)
                    probe_result = (
                        probe(target_id=target_id)
                        if callable(probe)
                        else basic_auth.state(target_id=target_id)
                    )
                    if not isinstance(probe_result, Mapping):
                        raise BrowserUnavailable("invalid Basic Auth probe state")
                    self._send_json(200, probe_result)
                    return
                elif self.path == "/broker/basic/submit":
                    if not self._broker_authorized() or basic_auth is None:
                        self._send_json(401, {"ok": False, "error_code": "unauthorized"})
                        return
                    payload = json.loads(self._read_text())
                    if not isinstance(payload, dict):
                        raise ValueError("Basic Auth payload must be an object")
                    origin = payload.get("origin")
                    username = payload.get("username")
                    password = payload.get("password")
                    target_id = payload.get("target_id")
                    success_path = payload.get("success_path")
                    if not all(
                        isinstance(value, str)
                        for value in (origin, username, password, target_id, success_path)
                    ):
                        raise ValueError("Basic Auth payload is invalid")
                    assert isinstance(origin, str)
                    assert isinstance(username, str)
                    assert isinstance(password, str)
                    assert isinstance(target_id, str)
                    assert isinstance(success_path, str)
                    basic_auth.submit(
                        origin,
                        username,
                        password,
                        target_id=target_id,
                        success_path=success_path,
                    )
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
                try:
                    binding_listener(binding)
                except Exception:  # noqa: BLE001 - listener must never abort the push
                    # The identity rebind already happened; a listener fault
                    # (e.g. download-watcher maintenance) must not turn a
                    # successful adoption into a dead handler/connection.
                    self.log_error("binding listener raised; push still accepted")
            self._send_json(200, {"ok": True})

        def _broker_authorized(self) -> bool:
            candidate = self.headers.get("X-CB-Broker-Secret", "")
            return bool(
                basic_auth is not None
                and len(broker_submit_secret) >= 16
                and hmac.compare_digest(candidate, broker_submit_secret)
            )

        def _read_text(self) -> str:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid body length") from exc
            if length <= 0 or length > _MAX_BODY:
                raise ValueError("invalid body length")
            return self.rfile.read(length).decode("utf-8")

        def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
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
