"""HTTP control surface for the owner-bound router (control-api/v1).

Endpoints exposed by ``create_router_server``:

- ``GET  /health`` — bounded service health metadata.
- ``GET  /ready``  — bounded readiness metadata.
- ``POST /v1/session``        — enqueue the authenticated edge into the
  router session store and assign the next free slot.
- ``GET  /v1/session``        — fetch the authenticated edge's current
  session (no other principal's record is readable).
- ``POST /v1/session/leave``  — release the caller's current session and
  free the slot.
- ``POST /v1/slot/<slot>/<op>`` — dispatch a bounded lifecycle command
  to the configured slot supervisor (``wake`` | ``suspend`` |
  ``recreate``).

Identity is resolved server-side from the authenticated edge headers via
``IdentityLinkClient``. ``Remote-Email`` is never used as an identity
authority (it is not even passed to the resolver). Every response is a
bounded JSON object containing only ``request_id``, ``status``, ``state``,
``error_code``, ``position``, ``offer_ttl_s``, ``session_ttl_s``, or
``session_id``/``slot_id`` as appropriate. Responses never contain
secrets, principal IDs, emails, binding contents, page values, or raw
exception text.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from cloudbrowser.edge_auth import parse_edge_identity
from cloudbrowser.identity_links import IdentityLinkClient, IdentityLinkClientError

from .agent_control_forwarder import (
    AgentControlForwarderError,
    AgentControlUnavailable,
)
from .sessions import RouterSession, RouterSessionStore, SessionStatus
from .supervisor_client import (
    SupervisorClient,
    SupervisorClientError,
    SupervisorUnavailable,
)


_MAX_BODY_BYTES = 4096
_MAX_REQUEST_ID = 128
_MAX_SLOT_ID = 64
_MAX_OP_LEN = 32
_SLOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_OP_SET = frozenset({"wake", "suspend", "recreate"})


@dataclass(frozen=True)
class _RouterIdentity:
    """Server-derived PMO principal for the current request."""

    principal_id: str


class _SupervisorPort(Protocol):
    """Subset of ``SupervisorClient`` the router API depends on."""

    def post_control(self, slot_id: str, *, operation: str, request_id: str) -> dict[str, object]: ...


class _AgentControlPort(Protocol):
    """Subset of ``AgentControlForwarder`` the router API depends on."""

    known_slots: frozenset[str]

    def forward(
        self,
        slot_id: str,
        *,
        binding: object,
        operation: str,
        params: Mapping[str, object],
        request_id: str,
    ) -> dict[str, object]: ...


_AGENT_ALLOWED_OPERATIONS = frozenset({"navigate", "click", "type", "page_info", "tabs_list"})
_AGENT_FORBIDDEN_OPERATIONS = frozenset(
    {
        "raw_cdp",
        "evaluate",
        "cookies",
        "storage",
        "network",
        "filesystem",
        "process",
        "credential_material",
        "password_values",
    }
)


def _bounded_text(value: str, *, limit: int) -> bool:
    if not isinstance(value, str) or not value or len(value) > limit:
        return False
    return all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)


def _request_id_from(payload: Mapping[str, object]) -> str:
    value = payload.get("request_id")
    if not _bounded_text(value, limit=_MAX_REQUEST_ID):  # type: ignore[arg-type]
        raise ValueError("request_id is invalid")
    return value  # type: ignore[return-value]


def _resolve_identity(
    *, headers: Mapping[str, object], client: IdentityLinkClient | None
) -> _RouterIdentity | None:
    if client is None:
        return None
    identity = parse_edge_identity({key: value for key, value in headers.items()})
    if identity is None:
        return None
    try:
        principal = client.resolve(identity)
    except IdentityLinkClientError:
        return None
    if not _bounded_text(principal, limit=256):  # type: ignore[arg-type]
        return None
    return _RouterIdentity(principal_id=principal)  # type: ignore[arg-type]


def _session_payload(session: RouterSession, *, now: float, request_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": session.session_id,
        "request_id": request_id,
        "status": session.status.value,
    }
    if session.slot_id is not None:
        payload["slot_id"] = session.slot_id
    if session.offer_expires_at is not None:
        payload["offer_ttl_s"] = round(max(0.0, session.offer_expires_at - now), 3)
    if session.session_expires_at is not None:
        payload["session_ttl_s"] = round(max(0.0, session.session_expires_at - now), 3)
    return payload


def _envelope(request_id: str, **fields: object) -> dict[str, object]:
    payload: dict[str, object] = {"request_id": request_id}
    payload.update(fields)
    return payload


def _coerce_str(value: object, *, default: str) -> str:
    """Return ``value`` only when it is a bounded string; otherwise ``default``."""
    if isinstance(value, str) and value and len(value) <= 64:
        return value
    return default


def _coerce_int(value: object, *, default: int) -> int:
    """Return ``value`` only when it is a non-negative integer; otherwise ``default``."""
    if isinstance(value, bool):  # bool is a subclass of int — exclude it
        return default
    if isinstance(value, int) and value >= 0:
        return value
    return default


class RouterApi:
    """Route the owner-bound router control plane to a session store + supervisor client."""

    def __init__(
        self,
        *,
        session_store: RouterSessionStore,
        supervisor_client: _SupervisorPort,
        identity_client: IdentityLinkClient | None,
        agent_control_forwarder: _AgentControlPort | None = None,
        component: str = "router",
    ) -> None:
        self._store = session_store
        self._supervisor = supervisor_client
        self._identity = identity_client
        self._agent_forwarder = agent_control_forwarder
        self._component = component

    # ---- HTTP handlers (one method per route) ----------------------------

    def health(self) -> dict[str, object]:
        return {"status": "ok", "component": self._component}

    def ready(self) -> dict[str, object]:
        return {"status": "ok", "component": self._component}

    def open_session(
        self, *, headers: Mapping[str, object], body: Mapping[str, object]
    ) -> tuple[int, dict[str, object]]:
        try:
            request_id = _request_id_from(body)
        except ValueError:
            return 200, _envelope("", status="failed", error_code="invalid_request")
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        try:
            session = self._store.enqueue(resolved.principal_id, request_id=request_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="enqueue_failed")
        try:
            now = self._store_clock()
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="store_unavailable")
        return 200, _session_payload(session, now=now, request_id=request_id)

    def get_session(
        self, *, headers: Mapping[str, object], request_id: str
    ) -> tuple[int, dict[str, object]]:
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        try:
            session = self._store.for_principal(resolved.principal_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="lookup_failed")
        if session is None:
            return 200, _envelope(request_id, status="waiting")
        try:
            now = self._store_clock()
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="store_unavailable")
        return 200, _session_payload(session, now=now, request_id=request_id)

    def leave_session(
        self, *, headers: Mapping[str, object], request_id: str
    ) -> tuple[int, dict[str, object]]:
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        try:
            session = self._store.for_principal(resolved.principal_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="lookup_failed")
        if session is None:
            return 200, _envelope(request_id, status="waiting")
        try:
            left = self._store.leave(session.session_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="leave_failed")
        return 200, _envelope(request_id, session_id=left.session_id, status=left.status.value)

    # ---- agent page-action relay (§3.1) ----------------------------------

    def agent_action(
        self,
        *,
        headers: Mapping[str, object],
        operation: str,
        body: Mapping[str, object],
    ) -> tuple[int, dict[str, object]]:
        """Relay one allowlisted page action to the caller's assigned slot.

        Slot, binding, browser, and generation are derived exclusively from
        the caller's own session; caller input supplies only the operation
        name and bounded params. Forbidden operations are refused locally.
        """
        request_id_value = body.get("request_id")
        if not _bounded_text(request_id_value, limit=_MAX_REQUEST_ID):  # type: ignore[arg-type]
            return 200, _envelope("", status="failed", error_code="invalid_request")
        request_id = request_id_value  # type: ignore[assignment]
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        forwarder = self._agent_forwarder
        if forwarder is None:
            return 200, _envelope(request_id, status="failed", error_code="agent_unavailable")
        if operation in _AGENT_FORBIDDEN_OPERATIONS:
            return 200, _envelope(request_id, status="failed", error_code="capability_denied")
        if operation not in _AGENT_ALLOWED_OPERATIONS:
            return 200, _envelope(request_id, status="failed", error_code="operation_not_supported")
        params = body.get("params", {})
        if not isinstance(params, dict):
            return 200, _envelope(request_id, status="failed", error_code="invalid_request")
        try:
            session = self._store.for_principal(resolved.principal_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="lookup_failed")
        if session is None or session.status is not SessionStatus.ACTIVE:
            return 200, _envelope(request_id, status="failed", error_code="session_not_found")
        if session.binding is None:
            return 200, _envelope(request_id, status="failed", error_code="no_binding")
        if session.slot_id is None:
            return 200, _envelope(request_id, status="failed", error_code="no_binding")
        if session.slot_id not in forwarder.known_slots:
            return 200, _envelope(request_id, status="failed", error_code="unknown_slot")
        try:
            result = forwarder.forward(
                session.slot_id,
                binding=session.binding,
                operation=operation,
                params=params,
                request_id=request_id,
            )
        except AgentControlForwarderError:
            return 200, _envelope(request_id, status="failed", error_code="invalid_request")
        except AgentControlUnavailable:
            return 200, _envelope(request_id, status="failed", error_code="agent_unavailable")
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="agent_unavailable")
        if not isinstance(result, dict) or not isinstance(result.get("status"), str):
            return 200, _envelope(request_id, status="failed", error_code="agent_unavailable")
        payload: dict[str, object] = {
            "request_id": request_id,
            "status": result["status"],
        }
        page = result.get("page")
        if isinstance(page, dict) and all(isinstance(key, str) for key in page):
            payload["page"] = {
                key: value
                for key, value in page.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        return 200, payload

    def slot_command(
        self,
        *,
        headers: Mapping[str, object],
        slot_id: str,
        operation: str,
        request_id: str,
    ) -> tuple[int, dict[str, object]]:
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        if not _SLOT_ID_RE.fullmatch(slot_id):
            return 200, _envelope(
                request_id, status="failed", error_code="invalid_request"
            )
        if operation not in _OP_SET:
            return 200, _envelope(
                request_id, status="failed", error_code="operation_not_supported"
            )
        known_slots = getattr(self._supervisor, "known_slots", None)
        if isinstance(known_slots, frozenset) and slot_id not in known_slots:
            return 200, _envelope(request_id, status="failed", error_code="unknown_slot")
        try:
            result = self._supervisor.post_control(
                slot_id, operation=operation, request_id=request_id
            )
        except SupervisorUnavailable:
            return 200, _envelope(request_id, status="failed", error_code="supervisor_unavailable")
        except SupervisorClientError:
            return 200, _envelope(request_id, status="failed", error_code="invalid_request")
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="operation_failed")
        return 200, _envelope(
            request_id,
            status=_coerce_str(result.get("status"), default="unknown"),
            state=_coerce_str(result.get("state"), default="unknown"),
            restored_count=_coerce_int(result.get("restored_count"), default=0),
        )

    # ---- helpers --------------------------------------------------------

    def _store_clock(self) -> float:
        # RouterSessionStore accepts a clock callable; surface its current time.
        clock = getattr(self._store, "_clock", None)
        if callable(clock):
            return float(clock())
        return 0.0


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


def _validate_health_origin() -> None:
    """Sanity check: empty implementation; placeholder for future hostname pinning."""


def create_router_server(
    api: RouterApi,
    *,
    address: tuple[str, int] = ("127.0.0.1", 8081),
) -> ThreadingHTTPServer:
    """Create a dependency-free stdlib HTTP server for the router control plane."""

    _validate_health_origin()
    host = address[0]
    if not isinstance(host, str) or not host or "\r" in host or "\n" in host:
        raise ValueError("address host must be a single-line string")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> Mapping[str, object]:
            length_header = self.headers.get("Content-Length")
            try:
                length = int(length_header or "0")
            except ValueError:
                raise ValueError("content-length is not an integer")
            if length < 0 or length > _MAX_BODY_BYTES:
                raise ValueError("payload too large")
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid JSON") from exc
            if not isinstance(decoded, dict):
                raise ValueError("request must be an object")
            return decoded

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_json(200, api.health())
                return
            if path == "/ready":
                self._send_json(200, api.ready())
                return
            if path == "/v1/session":
                status, payload = api.get_session(
                    headers=self.headers, request_id="req-1"
                )
                self._send_json(status, payload)
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            path = urlsplit(self.path).path
            try:
                if path == "/v1/session":
                    body = self._read_body()
                    status, payload = api.open_session(
                        headers=self.headers, body=body
                    )
                    self._send_json(status, payload)
                    return
                if path == "/v1/session/leave":
                    status, payload = api.leave_session(
                        headers=self.headers, request_id="req-1"
                    )
                    self._send_json(status, payload)
                    return
                if path.startswith("/v1/slot/"):
                    tail = path[len("/v1/slot/") :]
                    parts = tail.split("/")
                    if len(parts) != 2:
                        self._send_json(
                            200,
                            _envelope(
                                "req-1",
                                status="failed",
                                error_code="invalid_request",
                            ),
                        )
                        return
                    slot_id, operation = parts
                    status, payload = api.slot_command(
                        headers=self.headers,
                        slot_id=slot_id,
                        operation=operation,
                        request_id="req-1",
                    )
                    self._send_json(status, payload)
                    return
                if path.startswith("/v1/agent/"):
                    operation = path[len("/v1/agent/") :]
                    try:
                        body = self._read_body()
                    except ValueError:
                        body = {}
                    status, payload = api.agent_action(
                        headers=self.headers,
                        operation=operation,
                        body=body,
                    )
                    self._send_json(status, payload)
                    return
                self.send_error(404)
            except ValueError:
                self._send_json(
                    200,
                    _envelope(
                        "req-1",
                        status="failed",
                        error_code="invalid_request",
                    ),
                )

    return ThreadingHTTPServer(address, Handler)


__all__ = ["RouterApi", "create_router_server"]
