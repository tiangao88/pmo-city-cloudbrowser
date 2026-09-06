"""HTTP control API for owner-bound slot lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from typing import Any, Mapping

from cloudbrowser.browser_slots import BrowserBinding, BrowserOwnershipChanged, SlotSupervisor

_MIN_TRUSTED_SECRET_LENGTH = 16
_MAX_CONTROL_BODY = 4096


@dataclass(frozen=True)
class ControlRequest:
    """Caller input accepted by the control API; binding is server-derived."""

    operation: str
    request_id: str


class ControlApi:
    """Route only bounded lifecycle commands to a server-bound supervisor."""

    def __init__(
        self,
        supervisor: SlotSupervisor,
        binding: BrowserBinding,
        *,
        trusted_secret: str | None = None,
    ) -> None:
        if trusted_secret is not None:
            _validate_trusted_secret(trusted_secret)
        self._supervisor = supervisor
        self._binding = binding
        self._trusted_secret = trusted_secret

    def handle(self, request: ControlRequest) -> dict[str, object]:
        if not request.request_id or len(request.request_id) > 128:
            return {
                "request_id": request.request_id,
                "status": "failed",
                "error_code": "invalid_request",
            }
        try:
            if request.operation == "wake":
                result = self._supervisor.wake(self._binding)
            elif request.operation == "suspend":
                result = self._supervisor.suspend(self._binding)
            elif request.operation == "stop":
                result = self._supervisor.stop(self._binding)
            elif request.operation == "recreate":
                result = self._supervisor.recreate(self._binding)
            else:
                return {
                    "request_id": request.request_id,
                    "status": "unsupported",
                    "error_code": "operation_not_supported",
                }
        except BrowserOwnershipChanged:
            return {
                "request_id": request.request_id,
                "status": "failed",
                "error_code": "owner_mismatch",
            }
        except Exception:
            return {
                "request_id": request.request_id,
                "status": "failed",
                "error_code": "operation_failed",
            }
        return {
            "request_id": request.request_id,
            "status": result.status,
            "state": result.state.value,
            "restored_count": len(result.restored_urls),
        }


def _validate_trusted_secret(trusted_secret: str) -> None:
    if (
        not isinstance(trusted_secret, str)
        or len(trusted_secret) < _MIN_TRUSTED_SECRET_LENGTH
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in trusted_secret)
    ):
        raise ValueError("trusted_secret must be at least 16 printable characters")


def create_control_server(
    api: ControlApi,
    *,
    trusted_secret: str | None = None,
    address: tuple[str, int] = ("127.0.0.1", 8080),
) -> ThreadingHTTPServer:
    """Create a dependency-free server for POST /control and GET /health."""
    if trusted_secret is not None:
        _validate_trusted_secret(trusted_secret)
        if api._trusted_secret is None:
            api._trusted_secret = trusted_secret
        elif not hmac.compare_digest(api._trusted_secret, trusted_secret):
            raise ValueError("trusted_secret does not match ControlApi")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path != "/health":
                self.send_error(404)
                return
            self._send_json(200, {"status": "ok", "component": "slot-supervisor"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path != "/control":
                self.send_error(404)
                return
            if api._trusted_secret is None or not hmac.compare_digest(
                self.headers.get("X-CB-Trusted-Secret", ""), api._trusted_secret
            ):
                self._send_json(401, {"status": "failed", "error_code": "unauthorized"})
                return
            result: Mapping[str, object]
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > _MAX_CONTROL_BODY:
                    raise ValueError("invalid body length")
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError("request must be an object")
                operation = raw.get("operation")
                request_id = raw.get("request_id")
                if not isinstance(operation, str) or not isinstance(request_id, str):
                    raise ValueError("request fields are invalid")
                result = api.handle(ControlRequest(operation, request_id))
            except (ValueError, TypeError, json.JSONDecodeError):
                result = {
                    "request_id": "",
                    "status": "failed",
                    "error_code": "invalid_request",
                }
            self._send_json(200, dict(result))

        def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib contract
            return

    return ThreadingHTTPServer(address, Handler)
