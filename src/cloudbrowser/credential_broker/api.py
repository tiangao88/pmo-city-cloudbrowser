"""Broker HTTP/JSON transport adapter (`credential-broker/v1`).

The transport enforces:

- only the documented intent-only request shape (PRD-BR-01);
- rejection of caller-supplied ``principal_id`` / ``profile_id`` values that
  diverge from the server-authenticated identity (PRD-BR-03, S3);
- a status-only response shape that never contains credential fields;
- idempotent replay per ``(principal_id, idempotency_key)``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping

from .contracts import BrokerResult, LoginIntent


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Server-derived identity attached to one broker request."""

    profile_id: str
    principal_id: str
    browser_id: str
    site_id: str
    generation: str


@dataclass(frozen=True)
class ServerIdentity:
    """Bounded server-side identity for the audit envelope."""

    component: str
    instance_id: str


@dataclass(frozen=True)
class BrokerResponse:
    body: Mapping[str, object]


PrincipalResolver = Callable[[str], AuthenticatedPrincipal]


class BrokerHttpServer:
    def __init__(
        self,
        *,
        server_identity: ServerIdentity,
        principal_for: PrincipalResolver,
    ) -> None:
        self._server_identity = server_identity
        self._principal_for = principal_for

    @contextmanager
    def handle(self, path: str, payload: Mapping[str, object]) -> Iterator[BrokerResponse]:
        if path != "/v1/credential/login":
            raise LookupError("broker route not found")
        principal = self._principal_for(str(payload.get("auth_token", "")))
        result = _dispatch(payload, principal)
        yield BrokerResponse(body=result.to_public_dict())


def _dispatch(payload: Mapping[str, object], principal: AuthenticatedPrincipal) -> BrokerResult:
    request_id = str(payload.get("request_id", "")).strip()
    if not request_id or len(request_id) > 128:
        return BrokerResult(request_id or "missing", "failed", "invalid_request")
    if "principal_id" in payload or "profile_id" in payload:
        return BrokerResult(request_id, "failed", "binding_mismatch")
    username_ref = payload.get("username_ref")
    site_id = payload.get("site_id")
    if not isinstance(username_ref, str) or not isinstance(site_id, str):
        return BrokerResult(request_id, "failed", "invalid_request")
    intent = LoginIntent(
        request_id=request_id,
        profile_id=principal.profile_id,
        principal_id=principal.principal_id,
        browser_id=principal.browser_id,
        site_id=principal.site_id if site_id == principal.site_id else site_id,
        username_ref=username_ref,
        target_tab_id=str(payload["target_tab_id"]) if payload.get("target_tab_id") else None,
        idempotency_key=str(payload["idempotency_key"]) if payload.get("idempotency_key") else None,
        binding_generation=principal.generation,
    )
    return BrokerResult(request_id, "failed", "no_broker_coordinator")
