"""Deterministic broker coordinator with pre-fill binding revalidation."""

from __future__ import annotations

from typing import Callable, Mapping, Protocol

from .audit import AuditEmitter, AuditEventType, build_event
from .contracts import BrokerResult, LoginIntent, SiteDeclaration
from .idempotency import IdempotencyStore
from .service import AdapterResult, BindingMismatch, BrokerService, ResolvedBinding, StaleBinding


AdapterSelector = Callable[[str, object], "_AdapterCall"]


class _AdapterCall(Protocol):
    def __call__(self, declaration: object, material: object) -> AdapterResult: ...


class BrokerCoordinator:
    """Coordinate one status-only login without exposing broker material."""

    def __init__(
        self,
        *,
        resolve_initial: Callable[[LoginIntent], ResolvedBinding],
        resolve_pre_fill: Callable[[LoginIntent], ResolvedBinding],
        declarations: Mapping[str, object],
        adapter_selector: AdapterSelector,
        audit_emit: Callable[[AuditEventType, dict[str, object]], None] | None = None,
        emitter: AuditEmitter | None = None,
        idempotency: IdempotencyStore | None = None,
    ) -> None:
        self._idempotency = idempotency or IdempotencyStore()
        self._emitter = emitter
        self._audit_emit = audit_emit or (lambda event_type, fields: None)
        self._service = BrokerService(resolve_binding=resolve_initial, declarations=declarations)  # type: ignore[arg-type]
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

        # Initial binding validation is deliberately before credential fetch.
        declaration_or_result = self._service.validate_intent(intent)
        if isinstance(declaration_or_result, BrokerResult):
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, declaration_or_result.status, declaration_or_result.error_code)
            return self._remember(intent, declaration_or_result)
        declaration = declaration_or_result

        try:
            material = fetch_credentials(intent.username_ref)
        except LookupError:
            result = BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, result.status, result.error_code)
            return self._remember(intent, result)
        except Exception:
            result = BrokerResult(intent.request_id, "failed", "internal")
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, result.status, result.error_code)
            return self._remember(intent, result)

        # This is intentionally after fetch and before adapter invocation. A
        # reassignment or revocation therefore prevents the fill operation.
        try:
            current_binding = self._resolve_pre_fill(intent)
            BrokerService.validate_binding(intent, current_binding)
        except BindingMismatch:
            result = BrokerResult(intent.request_id, "failed", "binding_mismatch")
            self._audit(intent, AuditEventType.BROKER_OWNER_MISMATCH, result.status, result.error_code)
            return self._remember(intent, result)
        except StaleBinding:
            result = BrokerResult(intent.request_id, "failed", "stale_binding")
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, result.status, result.error_code)
            return self._remember(intent, result)
        except LookupError as exc:
            code = "grant_revoked" if str(exc) == "grant revoked" else "binding_unavailable"
            result = BrokerResult(intent.request_id, "not_shared", code)
            self._audit(intent, AuditEventType.BROKER_REVOKED, result.status, result.error_code)
            return self._remember(intent, result)

        try:
            adapter = self._adapter_selector(intent.site_id, declaration)
            outcome = adapter(declaration, material)
            result = BrokerService.result_from_adapter(intent.request_id, outcome)
        except ValueError:
            result = BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        except Exception:
            result = BrokerResult(intent.request_id, "failed", "internal")

        if result.status == "mfa_required":
            self._audit(intent, AuditEventType.BROKER_MFA_REQUESTED, result.status, result.error_code)
        elif result.status == "authenticated":
            self._audit(intent, AuditEventType.BROKER_LOGIN, result.status, result.error_code)
        else:
            self._audit(intent, AuditEventType.BROKER_LOGIN_FAILED, result.status, result.error_code)
        return self._remember(intent, result)

    def _remember(self, intent: LoginIntent, result: BrokerResult) -> BrokerResult:
        if intent.idempotency_key is not None:
            self._idempotency.record(intent.principal_id, intent.idempotency_key, result)
        return result

    def _audit(
        self,
        intent: LoginIntent,
        event_type: AuditEventType,
        outcome: str,
        error_code: str | None,
    ) -> None:
        if self._emitter is None:
            self._audit_emit(
                event_type,
                {
                    "request_id": intent.request_id,
                    "owner_id": intent.principal_id,
                    "outcome": outcome,
                    "error_code": error_code,
                },
            )
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
        self._audit_emit(event_type, event.body())


__all__ = ["BrokerCoordinator", "AdapterSelector"]
