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
- ``GET  /v1/roster``        — bounded roster of live sessions (status +
  non-authoritative display email captured at join) for every
  authenticated caller. Entries never contain principal IDs, bindings,
  or slot URLs.
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
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability

from .agent_control_forwarder import (
    AgentControlForwarderError,
    AgentControlUnavailable,
)
from .credential_broker_forwarder import (
    CredentialBrokerForwarderError,
    CredentialBrokerUnavailable,
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


class _CredentialBrokerPort(Protocol):
    def forward(self, capability: str, *, request_id: str) -> dict[str, object]: ...


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


_CREDENTIAL_OPERATION = "credential.login"
_CREDENTIAL_ALLOWED_FIELDS = frozenset({"request_id", "site_id", "target_tab_id"})
_CREDENTIAL_REFERENCE_FIELDS = frozenset({"username_ref", "grant_ref"})
_MAX_SITE_ID = 256
_MAX_TARGET_TAB_ID = 256
_MAX_AGENT_URL = 2048
_MAX_AGENT_TITLE = 4096
_MAX_AGENT_TABS = 32

_AGENT_ALLOWED_OPERATIONS = frozenset({"tab_open", "navigate", "click", "type", "page_info", "tabs_list"})
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
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit:
        return False
    return all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)


def _safe_observed_agent_url(value: object) -> bool:
    """Accept only the query-free HTTP(S) URLs exposed by agent-control."""
    if not _bounded_text(value, limit=_MAX_AGENT_URL):  # type: ignore[arg-type]
        return False
    parsed = urlsplit(value)  # type: ignore[arg-type]
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and ".." not in parsed.path
        and not parsed.query
        and not parsed.fragment
    )


def _bounded_agent_tabs(value: object) -> list[dict[str, str]]:
    """Validate and minimize a tab listing received across the slot boundary."""
    if not isinstance(value, list) or len(value) > _MAX_AGENT_TABS:
        raise ValueError("agent tab listing is invalid")
    tabs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("agent tab listing is invalid")
        tab_id, url, title = item.get("tab_id"), item.get("url"), item.get("title")
        if (
            not _bounded_text(tab_id, limit=_MAX_TARGET_TAB_ID)  # type: ignore[arg-type]
            or not _safe_observed_agent_url(url)
            or not _bounded_text(title, limit=_MAX_AGENT_TITLE)  # type: ignore[arg-type]
        ):
            raise ValueError("agent tab listing is invalid")
        tabs.append({"tab_id": tab_id, "url": url, "title": title})  # type: ignore[dict-item]
    return tabs


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


def _display_email_from(headers: Mapping[str, object]) -> str | None:
    """Extract the bounded non-authoritative display email, or None.

    The edge-authenticated ``remote-email`` header is display metadata only:
    it never participates in identity resolution and is captured solely so
    the roster can show who is queued. Anything absent, oversized, or
    carrying control characters is silently dropped, never stored.
    """
    value = headers.get("Remote-Email") or headers.get("remote-email")
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    return value


class RouterApi:
    """Route the owner-bound router control plane to a session store + supervisor client."""

    def __init__(
        self,
        *,
        session_store: RouterSessionStore,
        supervisor_client: _SupervisorPort,
        identity_client: IdentityLinkClient | None,
        agent_control_forwarder: _AgentControlPort | None = None,
        credential_broker_forwarder: _CredentialBrokerPort | None = None,
        capability_codec: CapabilityCodec | None = None,
        capability_audience: str = "credential-broker",
        deployment: str = "",
        capability_ttl_s: int = 60,
        clock=None,
        nonce_factory=None,
        component: str = "router",
    ) -> None:
        self._store = session_store
        self._supervisor = supervisor_client
        self._identity = identity_client
        self._agent_forwarder = agent_control_forwarder
        self._credential_broker = credential_broker_forwarder
        self._capability_codec = capability_codec
        self._capability_audience = capability_audience
        self._deployment = deployment or "unknown-deployment"
        self._capability_ttl_s = capability_ttl_s
        self._clock = clock
        self._nonce_factory = nonce_factory
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
            session = self._store.enqueue(
                resolved.principal_id,
                request_id=request_id,
                display_email=_display_email_from(headers),
            )
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

    def roster(
        self, *, headers: Mapping[str, object]
    ) -> tuple[int, dict[str, object]]:
        """Return who is waiting and who holds a slot (identity-gated).

        Every authenticated caller sees the same bounded roster: one entry
        per live session with its status and, when captured at join, its
        non-authoritative display email. Entries never include principal
        IDs, bindings, slot URLs, or session ids.
        """
        request_id = "roster"
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        try:
            entries = self._store.roster()
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="roster_failed")
        return 200, _envelope(request_id, status="ok", entries=entries)

    def activate_session(
        self,
        *,
        headers: Mapping[str, object],
        request_id: str,
    ) -> tuple[int, dict[str, object]]:
        """Wake the caller's assigned slot and flip OFFERED -> ACTIVE.

        The supervisor receives the server-minted session binding on
        ``wake``; slot, binding, and browser are derived exclusively from
        the caller's own session. On supervisor failure the session stays
        ``OFFERED`` and the supervisor's bounded error code is surfaced.
        """
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        try:
            session = self._store.for_principal(resolved.principal_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="lookup_failed")
        if session is None:
            return 200, _envelope(request_id, status="failed", error_code="session_not_found")
        if session.status not in {SessionStatus.OFFERED, SessionStatus.ACTIVE}:
            return 200, _envelope(request_id, status="failed", error_code="session_not_found")
        if session.binding is None or session.slot_id is None:
            return 200, _envelope(request_id, status="failed", error_code="no_binding")
        if session.slot_id not in self._supervisor.known_slots:
            return 200, _envelope(request_id, status="failed", error_code="unknown_slot")
        try:
            result = self._supervisor.post_control(
                session.slot_id,
                operation="wake",
                request_id=request_id,
                binding=session.binding,
            )
        except SupervisorUnavailable:
            return 200, _envelope(request_id, status="failed", error_code="supervisor_unavailable")
        except SupervisorClientError:
            return 200, _envelope(request_id, status="failed", error_code="invalid_request")
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="operation_failed")
        if not isinstance(result, dict) or result.get("status") not in {"ready", "ok", "adopted"}:
            error_code = "operation_failed"
            raw_code = result.get("error_code") if isinstance(result, dict) else None
            if isinstance(raw_code, str) and raw_code in {
                "slot_mismatch",
                "owner_mismatch",
                "operation_failed",
            }:
                error_code = raw_code
            return 200, _envelope(request_id, status="failed", error_code=error_code)
        try:
            activated = self._store.activate(session.session_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="activate_failed")
        try:
            now = self._store_clock()
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="store_unavailable")
        return 200, _session_payload(activated, now=now, request_id=request_id)

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
        required_target = operation not in {"tabs_list", "tab_open"}
        target_tab_id = params.get("target_tab_id")
        if required_target and (not isinstance(target_tab_id, str) or not _bounded_text(target_tab_id, limit=_MAX_TARGET_TAB_ID)):
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
        page = result.get("page")
        safe_page: dict[str, str] | list[dict[str, str]] | None = None
        if operation == "tabs_list":
            if result["status"] == "ok":
                try:
                    safe_page = _bounded_agent_tabs(page)
                except ValueError:
                    return 200, _envelope(request_id, status="failed", error_code="agent_unavailable")
        elif isinstance(page, dict) and all(isinstance(key, str) for key in page):
            safe_page = {
                key: value
                for key, value in page.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        # Sliding TTL: a successfully relayed action is authenticated work,
        # so the caller's active lease slides forward. Renewal is
        # best-effort — the page action already happened, so a renewal
        # hiccup must not turn it into a reported failure.
        try:
            self._store.renew(resolved.principal_id)
        except Exception:
            pass
        payload: dict[str, object] = {
            "request_id": request_id,
            "status": result["status"],
        }
        if safe_page is not None:
            payload["page"] = safe_page
        return 200, payload

    def credential_login(
        self,
        *,
        headers: Mapping[str, object],
        body: Mapping[str, object],
    ) -> tuple[int, dict[str, object]]:
        """Mint and forward one server-bound, opaque login capability."""
        request_id = body.get("request_id")
        site_id = body.get("site_id")
        target_tab_id = body.get("target_tab_id")
        if (
            not _bounded_text(request_id, limit=_MAX_REQUEST_ID)  # type: ignore[arg-type]
            or not _bounded_text(site_id, limit=_MAX_SITE_ID)  # type: ignore[arg-type]
            or not _bounded_text(target_tab_id, limit=_MAX_TARGET_TAB_ID)  # type: ignore[arg-type]
            or set(body) - _CREDENTIAL_ALLOWED_FIELDS
            or _CREDENTIAL_REFERENCE_FIELDS.intersection(body)
        ):
            safe_request_id = (
                str(request_id)
                if _bounded_text(request_id, limit=_MAX_REQUEST_ID)  # type: ignore[arg-type]
                else ""
            )
            return 200, _envelope(
                safe_request_id,
                status="failed",
                error_code="invalid_request",
            )
        request_id = request_id  # type: ignore[assignment]
        site_id = site_id  # type: ignore[assignment]
        target_tab_id = target_tab_id  # type: ignore[assignment]
        resolved = _resolve_identity(headers=headers, client=self._identity)
        if resolved is None:
            return 401, _envelope(request_id, status="failed", error_code="unauthorized")
        if self._credential_broker is None or self._capability_codec is None:
            return 200, _envelope(request_id, status="failed", error_code="broker_unavailable")
        try:
            session = self._store.for_principal(resolved.principal_id)
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="lookup_failed")
        if session is None or session.status is not SessionStatus.ACTIVE:
            return 200, _envelope(request_id, status="failed", error_code="session_not_found")
        binding = session.binding
        if binding is None or session.slot_id is None:
            return 200, _envelope(request_id, status="failed", error_code="no_binding")
        if binding.principal_id != resolved.principal_id:
            return 200, _envelope(request_id, status="failed", error_code="owner_mismatch")
        now = self._capability_now()
        try:
            capability = CredentialCapability(
                profile_id=binding.profile_id,
                principal_id=resolved.principal_id,
                browser_id=binding.browser_id,
                generation=binding.generation,
                site_id=site_id,
                target_tab_id=target_tab_id,
                operation=_CREDENTIAL_OPERATION,
                request_id=request_id,
                audience=self._capability_audience,
                deployment=self._deployment,
                issued_at=now,
                expires_at=now + self._capability_ttl_s,
                nonce=self._new_nonce(),
            )
            token = self._capability_codec.encode(capability)
            result = self._credential_broker.forward(token, request_id=request_id)
        except (ValueError, CredentialBrokerForwarderError):
            return 200, _envelope(request_id, status="failed", error_code="invalid_request")
        except CredentialBrokerUnavailable:
            return 200, _envelope(request_id, status="failed", error_code="broker_unavailable")
        except Exception:
            return 200, _envelope(request_id, status="failed", error_code="broker_unavailable")
        if not isinstance(result, dict):
            return 200, _envelope(request_id, status="failed", error_code="broker_unavailable")
        payload = {
            "request_id": request_id,
            "status": result.get("status", "failed"),
            "error_code": result.get("error_code"),
            "duration_ms": result.get("duration_ms", 0),
        }
        if not isinstance(payload["status"], str) or not isinstance(payload["duration_ms"], int):
            return 200, _envelope(request_id, status="failed", error_code="broker_unavailable")
        return 200, payload

    def _capability_now(self) -> int:
        import time

        return int(self._clock() if callable(self._clock) else time.time())

    def _new_nonce(self) -> str:
        import secrets

        value = self._nonce_factory() if callable(self._nonce_factory) else secrets.token_urlsafe(24)
        if not isinstance(value, str) or not value:
            raise ValueError("nonce is invalid")
        return value

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
            if path == "/v1/roster":
                status, payload = api.roster(headers=dict(self.headers.items()))
                self._send_json(status, payload)
                return
            if path == "/v1/credential/login":
                self.send_error(405)
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            path = urlsplit(self.path).path
            try:
                if path == "/v1/session":
                    body = self._read_body()
                    status, payload = api.open_session(
                        headers=dict(self.headers.items()), body=body
                    )
                    self._send_json(status, payload)
                    return
                if path == "/v1/session/leave":
                    status, payload = api.leave_session(
                        headers=dict(self.headers.items()), request_id="req-1"
                    )
                    self._send_json(status, payload)
                    return
                if path == "/v1/session/activate":
                    status, payload = api.activate_session(
                        headers=dict(self.headers.items()), request_id="req-1"
                    )
                    self._send_json(status, payload)
                    return
                if path == "/v1/credential/login":
                    body = self._read_body()
                    status, payload = api.credential_login(
                        headers=dict(self.headers.items()), body=body
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
                        headers=dict(self.headers.items()),
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
                        headers=dict(self.headers.items()),
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
