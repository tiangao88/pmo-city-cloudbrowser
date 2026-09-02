"""Deterministic broker coordinator.

Wraps ``BrokerService`` semantics with:

- binding re-resolution immediately before fill (PRD-BR-09);
- audit emission in the ``cloudbrowser.audit.v1`` envelope;
- idempotent replay routing, owned externally via the API layer;
- a strict "no credential-shaped payload" rule for the audit transport.
"""

from __future__ import annotations

from typing import Callable, Mapping, Protocol

from ..security import BROKER_STATUS_VALUES  # noqa: F401 - implicit contract
from .audit import AuditEventType, AuditEmitter, build_event
from .contracts import BrokerResult, LoginIntent, SiteDeclaration
from .idempotency import IdempotencyStore
from .service import AdapterResult, BindingMismatch, BrokerService, ResolvedBinding, StaleBinding


AdapterSelector = Callable[[str, SiteDeclaration], "_AdapterCall"]


class _AdapterCall(Protocol):
    def __call__(self, declaration: SiteDeclaration, material: object) -> AdapterResult: ...


class BrokerCoordinator:
    def __init__(
        self,
        *,
        resolve_initial: Callable[[LoginIntent], ResolvedBinding],
        resolve_pre_fill: Callable[[LoginIntent], ResolvedBinding],
        declarations: Mapping[str, SiteDeclaration],
        adapter_selector: AdapterSelector,
        audit_emit: Callable[[AuditEventType, dict[str, object]], None] | None = None,
        emitter: AuditEmitter | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self._idempotency = idempotency or IdempotencyStore()
        self._emitter = emitter
        self._audit_emit = audit_emit or (lambda et, fields: None)
        self._service = BrokerService(resolve_binding=resolve_initial, declarations=declarations)
        self._resolve_pre_fill = resolve_pre_fill
        self._adapter_selector = adapter_selector

    def execute(
        self,
        intent: LoginIntent,
        *,
        fetch_credentials: Callable[[str], object],
    ) -> BrokerResult:
        if intent.idempotency_key is not None:
            cached = self._idempotency.replay(intent.principal_id, intent.idempotency_key)
            if cached is not None:
                return cached

        binding = self._resolve_pre_fill(intent)
        try:
            self._service._validate_binding(intent, binding)  # type: ignore[attr-defined]
        except BindingMismatch:
            return self._reject(intent, "binding_mismatch", AuditEventType.BROKER_OWNER_MISMATCH)
        except StaleBinding:
            return self._reject(intent, "stale_binding", AuditEventType.BROKER_LOGIN_FAILED)

        declaration_or_result = self._service.validate_intent(intent)
        if isinstance(declaration_or_result, BrokerResult):
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, "failed", declaration_or_result.error_code)
            return declaration_or_result
        declaration = declaration_or_result

        try:
            material = fetch_credentials(intent.username_ref)
        except LookupError:
            result = BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, "not_shared", result.error_code)
            return result

        adapter = self._adapter_selector(intent.site_id, declaration)
        try:
            outcome = adapter(declaration, material)
        except ValueError as exc:
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, "failed", "adapter_invalid_target")
            return BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        if outcome.status not in {"authenticated", "mfa_required", "failed"}:
            result = BrokerResult(intent.request_id, "failed", "adapter_result_invalid")
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, "failed", result.error_code)
            return result
        if outcome.status == "authenticated" and not outcome.identity_verified:
            result = BrokerResult(intent.request_id, "failed", "identity_unverified")
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, "failed", result.error_code)
            return result

        if outcome.status == "mfa_required":
            self._audit(intent, AuditEventType.BROKER_MFA_REQUESTED, "mfa_required", None)
            result = BrokerResult(intent.request_id, "mfa_required")
        else:
            self._audit(intent, AuditEventType.BROKER_LOGIN, outcome.status, None)
            result = BrokerResult(intent.request_id, outcome.status)

        if intent.idempotency_key is not None:
            self._idempotency.record(intent.principal_id, intent.idempotency_key, result)
        return result

    def _reject(
        self,
        intent: LoginIntent,
        error_code: str,
        event_type: AuditEventType,
    ) -> BrokerResult:
        result = BrokerResult(intent.request_id, "failed", error_code)
        self._audit(intent, event_type, "failed", error_code)
        return result

    def _audit(
        self,
        intent: LoginIntent,
        event_type: AuditEventType,
        outcome: str,
        error_code: str | None,
    ) -> None:
        payload = {
            "request_id": intent.request_id,
            "owner_id": intent.principal_id,
            "outcome": outcome,
            "error_code": error_code,
        }
        if self._emitter is None:
            self._audit_emit(event_type, payload)
            return
        event = build_event(
            emitter=self._emitter,
            event_type=event_type,
            owner_id=intent.principal_id,
            outcome=outcome,
            error_code=error_code,
            duration_ms=0,
            request_id=intent.request_id,
        )
        body = event.body()
        for forbidden in ("username", "password", "secret"):
            body.pop(forbidden, None)
        self._audit_emit(event_type, body)
