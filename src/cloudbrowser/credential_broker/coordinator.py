"""Deterministic broker coordinator with mandatory authorization checks."""

from __future__ import annotations

from typing import Callable, Mapping, Protocol
from cloudbrowser.broker_jobs import JobsUnavailable

from cloudbrowser.browser_slots.transport import BrowserUnavailable

from .audit import AuditEmitter, AuditEventType, build_event
from .contracts import (
    AuthorizationChanged,
    BrokerResult,
    GrantAuthorization,
    LoginIntent,
)
from .deadline import BrokerDeadline, BrokerDeadlineExceeded, invoke_with_deadline
from .service import (
    AdapterResult,
    BindingMismatch,
    BrokerService,
    DependencyUnavailable,
    GrantResolver,
    ResolvedBinding,
    StaleBinding,
    TargetPreflight,
)

AdapterSelector = Callable[[str, object, LoginIntent], "_AdapterCall"]


class _AdapterCall(Protocol):
    def __call__(self, declaration: object, material: object, /) -> AdapterResult: ...


class AuthorizationGate(Protocol):
    """Atomically authorize and hold one grant through a browser side effect."""

    supplies_material: bool

    def run_authorized(
        self,
        authorization: GrantAuthorization,
        operation: Callable[[object], AdapterResult],
    ) -> AdapterResult: ...


class _TestOnlyGrantResolver:
    """Compatibility helper unreachable from production HTTP assembly."""

    def __init__(self, username_ref: str = "test-only") -> None:
        self._username_ref = username_ref

    def resolve(
        self,
        binding: ResolvedBinding,
        site_id: str,
        target_tab_id: str,
    ) -> GrantAuthorization:
        return GrantAuthorization(
            username_ref=self._username_ref,
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
            site_id=site_id,
            target_tab_id=target_tab_id,
            epoch=1,
        )


class BrokerCoordinator:
    """Coordinate one status-only login without exposing broker material."""

    def __init__(
        self,
        *,
        resolve_initial: Callable[[LoginIntent], ResolvedBinding],
        resolve_pre_fill: Callable[[LoginIntent], ResolvedBinding],
        declarations: Mapping[str, object],
        adapter_selector: AdapterSelector,
        grant_resolver: GrantResolver | None = None,
        target_preflight: TargetPreflight | Callable[[LoginIntent, object], object] | None = None,
        authorization_gate: AuthorizationGate | None = None,
        audit_emit: Callable[[AuditEventType, dict[str, object]], None] | None = None,
        emitter: AuditEmitter | None = None,
        test_only_allow_compatibility_authorization: bool = False,
        broker_jobs=None,
    ) -> None:
        if not test_only_allow_compatibility_authorization:
            if grant_resolver is None:
                raise TypeError("grant_resolver is required")
            if target_preflight is None:
                raise TypeError("target_preflight is required")
            if authorization_gate is None:
                candidate = getattr(grant_resolver, "run_authorized", None)
                if callable(candidate):
                    authorization_gate = grant_resolver  # type: ignore[assignment]
        self._test_only_compatibility = test_only_allow_compatibility_authorization
        self._emitter = emitter
        self._audit_emit = audit_emit or (lambda event_type, fields: None)
        self._service = BrokerService(
            resolve_binding=resolve_initial,
            declarations=declarations,  # type: ignore[arg-type]
            grant_resolver=grant_resolver or _TestOnlyGrantResolver(),
            target_preflight=target_preflight or (lambda *_: object()),
        )
        self._resolve_pre_fill = resolve_pre_fill
        self._adapter_selector = adapter_selector
        self._authorization_gate = authorization_gate
        self._broker_jobs = broker_jobs

    def admission_epoch(self):
        return self._broker_jobs.snapshot() if self._broker_jobs is not None else None

    def _revalidate_grant_before_fetch(
        self,
        intent: LoginIntent,
        initial_grant: GrantAuthorization,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> bool:
        """Recheck grant epoch/scope immediately before the Vault read."""
        current_grant = self._service.recheck_grant(
            intent,
            initial_grant,
            deadline=deadline,
        )
        return current_grant == initial_grant

    def execute(
        self, intent, *, fetch_credentials, deadline=None, admission_epoch=None,
    ) -> BrokerResult:
        if self._broker_jobs is None:
            return self._execute(intent, fetch_credentials=fetch_credentials, deadline=deadline)
        try:
            epoch = admission_epoch if admission_epoch is not None else self.admission_epoch()
            with self._broker_jobs.job(epoch):
                return self._execute(intent, fetch_credentials=fetch_credentials, deadline=deadline)
        except (JobsUnavailable, OSError):
            return self._fail(intent, "browser_control_paused")

    def _execute(
        self,
        intent: LoginIntent,
        *,
        fetch_credentials: Callable[[str], object],
        deadline: BrokerDeadline | None = None,
    ) -> BrokerResult:
        if self._test_only_compatibility:
            return self._execute_test_only_compatibility(
                intent, fetch_credentials=fetch_credentials, deadline=deadline
            )

        try:
            if deadline is not None:
                deadline.check()
            declaration_or_result = self._service.validate_intent(intent, deadline=deadline)
        except BrokerDeadlineExceeded:
            return self._fail(intent, "deadline_exceeded")
        except BrowserUnavailable:
            return self._fail(intent, "browser_unavailable")
        except DependencyUnavailable:
            return self._fail(intent, "dependency_unavailable")
        if isinstance(declaration_or_result, BrokerResult):
            self._audit_result(intent, declaration_or_result)
            return declaration_or_result
        declaration = declaration_or_result

        try:
            initial_binding = self._service.resolve_binding(intent, deadline=deadline)
            initial_target = self._service.preflight_target(
                intent, declaration, deadline=deadline
            )
            initial_grant = self._service.resolve_grant(
                intent, initial_binding, deadline=deadline
            )
            # Re-resolve the grant, including its authorization epoch, immediately
            # before reading Vault material so revoke/reassign cannot race the fetch.
            if not self._revalidate_grant_before_fetch(
                intent,
                initial_grant,
                deadline=deadline,
            ):
                return self._fail(intent, "grant_changed")
        except BindingMismatch:
            return self._fail(intent, "binding_mismatch", owner_mismatch=True)
        except StaleBinding:
            return self._fail(intent, "stale_binding")
        except LookupError as exc:
            return self._not_shared(intent, exc)
        except ValueError:
            return self._fail(intent, "invalid_target")
        except BrokerDeadlineExceeded:
            return self._fail(intent, "deadline_exceeded")
        except BrowserUnavailable:
            return self._fail(intent, "browser_unavailable")
        except DependencyUnavailable:
            return self._fail(intent, "dependency_unavailable")

        gate_supplies_material = self._authorization_gate is not None and bool(
            getattr(self._authorization_gate, "supplies_material", False)
        )
        if not gate_supplies_material:
            try:
                material = invoke_with_deadline(
                    fetch_credentials,
                    initial_grant.username_ref,
                    deadline=deadline,
                )
            except BrokerDeadlineExceeded:
                return self._fail(intent, "deadline_exceeded")
            except BrowserUnavailable:
                return self._fail(intent, "browser_unavailable")
            except DependencyUnavailable:
                return self._fail(intent, "dependency_unavailable")
        else:
            material = None

        try:
            current_binding = invoke_with_deadline(
                self._resolve_pre_fill,
                intent,
                deadline=deadline,
            )
            BrokerService.validate_binding(intent, current_binding)
            current_target = self._service.preflight_target(
                intent, declaration, deadline=deadline
            )
            current_grant = self._service.resolve_grant(
                intent, current_binding, deadline=deadline
            )
            if current_grant != initial_grant:
                return self._fail(intent, "grant_changed")
            if current_target != initial_target:
                return self._fail(intent, "target_changed")
        except BindingMismatch:
            return self._fail(intent, "binding_mismatch", owner_mismatch=True)
        except StaleBinding:
            return self._fail(intent, "stale_binding")
        except LookupError as exc:
            return self._not_shared(intent, exc)
        except ValueError:
            return self._fail(intent, "invalid_target")
        except BrokerDeadlineExceeded:
            return self._fail(intent, "deadline_exceeded")
        except BrowserUnavailable:
            return self._fail(intent, "browser_unavailable")
        except DependencyUnavailable:
            return self._fail(intent, "dependency_unavailable")

        try:
            adapter = invoke_with_deadline(
                self._adapter_selector,
                intent.site_id,
                declaration,
                intent,
                deadline=deadline,
            )

            def run_adapter(gated_material: object) -> AdapterResult:
                return invoke_with_deadline(
                    adapter,
                    declaration,
                    gated_material,
                    deadline=deadline,
                )

            if self._authorization_gate is None:
                outcome = run_adapter(material)
            elif gate_supplies_material:
                outcome = invoke_with_deadline(
                    self._authorization_gate.run_authorized,
                    initial_grant,
                    run_adapter,
                    deadline=deadline,
                )
            else:
                outcome = invoke_with_deadline(
                    self._authorization_gate.run_authorized,
                    initial_grant,
                    lambda _ignored: run_adapter(material),
                    deadline=deadline,
                )
            result = BrokerService.result_from_adapter(intent.request_id, outcome)
        except AuthorizationChanged:
            return self._fail(intent, "grant_changed")
        except LookupError as exc:
            return self._not_shared(intent, exc)
        except ValueError:
            result = BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        except BrokerDeadlineExceeded:
            result = BrokerResult(intent.request_id, "failed", "deadline_exceeded")
        except BrowserUnavailable:
            result = BrokerResult(intent.request_id, "failed", "browser_unavailable")
        except DependencyUnavailable:
            result = BrokerResult(intent.request_id, "failed", "dependency_unavailable")
        self._audit_result(intent, result)
        return result

    def _execute_test_only_compatibility(
        self,
        intent: LoginIntent,
        *,
        fetch_credentials: Callable[[str], object],
        deadline: BrokerDeadline | None = None,
    ) -> BrokerResult:
        """Preserve old unit seams, never selected by production runtime."""
        declaration_or_result = self._service.validate_intent(intent, deadline=deadline)
        if isinstance(declaration_or_result, BrokerResult):
            self._audit_result(intent, declaration_or_result)
            return declaration_or_result
        declaration = declaration_or_result
        if not intent.username_ref:
            return self._not_shared(intent, LookupError("grant unavailable"))
        try:
            initial_binding = self._service.resolve_binding(intent, deadline=deadline)
            target_id = intent.target_tab_id or "test-only-target"
            initial_grant = _TestOnlyGrantResolver(intent.username_ref).resolve(
                initial_binding,
                intent.site_id,
                target_id,
            )
            material = invoke_with_deadline(
                fetch_credentials,
                initial_grant.username_ref,
                deadline=deadline,
            )
            current_binding = invoke_with_deadline(
                self._resolve_pre_fill,
                intent,
                deadline=deadline,
            )
            BrokerService.validate_binding(intent, current_binding)
            current_grant = _TestOnlyGrantResolver(intent.username_ref).resolve(
                current_binding,
                intent.site_id,
                target_id,
            )
            if current_grant != initial_grant:
                return self._fail(intent, "binding_mismatch", owner_mismatch=True)
        except BindingMismatch:
            return self._fail(intent, "binding_mismatch", owner_mismatch=True)
        except StaleBinding:
            return self._fail(intent, "stale_binding")
        except LookupError as exc:
            return self._not_shared(intent, exc)
        except BrokerDeadlineExceeded:
            return self._fail(intent, "deadline_exceeded")
        except BrowserUnavailable:
            return self._fail(intent, "browser_unavailable")
        except DependencyUnavailable:
            return self._fail(intent, "dependency_unavailable")
        try:
            adapter = invoke_with_deadline(
                self._adapter_selector,
                intent.site_id,
                declaration,
                intent,
                deadline=deadline,
            )
            outcome = invoke_with_deadline(adapter, declaration, material, deadline=deadline)
            result = BrokerService.result_from_adapter(intent.request_id, outcome)
        except ValueError:
            result = BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        except BrokerDeadlineExceeded:
            result = BrokerResult(intent.request_id, "failed", "deadline_exceeded")
        except BrowserUnavailable:
            result = BrokerResult(intent.request_id, "failed", "browser_unavailable")
        except DependencyUnavailable:
            result = BrokerResult(intent.request_id, "failed", "dependency_unavailable")
        self._audit_result(intent, result)
        return result

    def _fail(
        self,
        intent: LoginIntent,
        error_code: str,
        *,
        owner_mismatch: bool = False,
    ) -> BrokerResult:
        result = BrokerResult(intent.request_id, "failed", error_code)
        event = (
            AuditEventType.BROKER_OWNER_MISMATCH
            if owner_mismatch
            else AuditEventType.BROKER_LOGIN_FAILED
        )
        self._audit(intent, event, result.status, result.error_code)
        return result

    def _not_shared(self, intent: LoginIntent, exc: LookupError) -> BrokerResult:
        code = "grant_revoked" if str(exc) == "grant revoked" else "grant_unavailable"
        result = BrokerResult(intent.request_id, "not_shared", code)
        self._audit(intent, AuditEventType.BROKER_REVOKED, result.status, result.error_code)
        return result

    def _audit_result(self, intent: LoginIntent, result: BrokerResult) -> None:
        if result.status == "mfa_required":
            event = AuditEventType.BROKER_MFA_REQUESTED
        elif result.status == "authenticated":
            event = AuditEventType.BROKER_LOGIN
        else:
            event = AuditEventType.BROKER_LOGIN_FAILED
        self._audit(intent, event, result.status, result.error_code)

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
