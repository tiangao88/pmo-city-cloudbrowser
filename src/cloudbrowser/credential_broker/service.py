from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, TypeVar

from cloudbrowser.browser_slots.transport import BrowserUnavailable

from ..security import BROKER_STATUS_VALUES
from .contracts import BrokerResult, GrantAuthorization, LoginIntent, SiteDeclaration
from .deadline import BrokerDeadline, invoke_with_deadline

AdapterDeclaration = TypeVar("AdapterDeclaration", contravariant=True)
AdapterMaterial = TypeVar("AdapterMaterial", contravariant=True)


class DependencyUnavailable(RuntimeError):
    """Expected non-browser dependency failure safe to map to a bounded result."""


class GrantResolver(Protocol):
    """Resolve one server-owned grant item for an authenticated binding."""

    def resolve(
        self,
        binding: "ResolvedBinding",
        site_id: str,
        target_tab_id: str,
    ) -> GrantAuthorization: ...


class TargetPreflight(Protocol):
    """Probe the actual target without reading or returning credentials."""

    def preflight(
        self,
        intent: LoginIntent,
        declaration: object,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> object: ...


class LoginAdapter(Protocol[AdapterDeclaration, AdapterMaterial]):
    """Internal adapter contract used by the broker service."""

    def __call__(
        self, declaration: AdapterDeclaration, material: AdapterMaterial
    ) -> "AdapterResult": ...


@dataclass(frozen=True)
class ResolvedBinding:
    """Server-authoritative identity and browser binding for one request."""

    profile_id: str
    principal_id: str
    browser_id: str
    site_id: str
    generation: str
    revoked: bool = False


@dataclass(frozen=True)
class AdapterResult:
    """Internal adapter outcome; only status/error metadata crosses the boundary."""

    status: str
    identity_verified: bool
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in BROKER_STATUS_VALUES:
            raise ValueError("invalid adapter status")
        if not isinstance(self.identity_verified, bool):
            raise ValueError("identity_verified must be boolean")
        if self.error_code is not None and (
            not isinstance(self.error_code, str)
            or not self.error_code
            or len(self.error_code) > 64
            or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for char in self.error_code
            )
        ):
            raise ValueError("error_code must be bounded")


class BindingMismatch(ValueError):
    """Raised when a request assertion differs from server-authoritative state."""


class StaleBinding(ValueError):
    """Raised when the request generation no longer matches the live browser."""


class BrokerService:
    """Validate broker intent and execute a status-only broker operation."""

    def __init__(
        self,
        resolve_binding: Callable[[LoginIntent], ResolvedBinding],
        declarations: Mapping[str, SiteDeclaration],
        *,
        grant_resolver: GrantResolver | None = None,
        target_preflight: TargetPreflight | Callable[[LoginIntent, object], object] | None = None,
    ) -> None:
        self._resolve_binding = resolve_binding
        self._declarations = dict(declarations)
        self._grant_resolver = grant_resolver
        self._target_preflight = target_preflight

    def resolve_binding(
        self,
        intent: LoginIntent,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> ResolvedBinding:
        binding = invoke_with_deadline(self._resolve_binding, intent, deadline=deadline)
        self.validate_binding(intent, binding)
        return binding

    def preflight_target(
        self,
        intent: LoginIntent,
        declaration: object,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> object:
        """Probe the exact target before any credential fetch or fill."""
        if self._target_preflight is None:
            raise ValueError("target preflight is required")
        method = getattr(self._target_preflight, "preflight", self._target_preflight)
        if not callable(method):
            raise TypeError("target preflight is not callable")
        if callable(method):
            try:
                proof = invoke_with_deadline(method, intent, declaration, deadline=deadline)
            except TypeError as exc:
                if deadline is None or "deadline" not in str(exc):
                    raise
                proof = method(intent, declaration)
        if proof is False:
            raise ValueError("target preflight rejected the actual target")
        if deadline is not None:
            deadline.check()
        return proof

    def resolve_grant(
        self,
        intent: LoginIntent,
        binding: ResolvedBinding,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> GrantAuthorization:
        """Resolve a complete server-owned grant authorization."""
        if self._grant_resolver is None:
            raise LookupError("grant unavailable")
        target_tab_id = intent.target_tab_id
        if not isinstance(target_tab_id, str) or not target_tab_id:
            raise ValueError("target_tab_id is required")
        resolver = getattr(self._grant_resolver, "resolve", self._grant_resolver)
        if not callable(resolver):
            raise TypeError("grant resolver is not callable")
        authorization = invoke_with_deadline(
            resolver,
            binding,
            intent.site_id,
            target_tab_id,
            deadline=deadline,
        )
        if not isinstance(authorization, GrantAuthorization):
            raise ValueError("grant resolver returned invalid authorization")
        if not authorization.matches(binding, intent.site_id, target_tab_id):
            raise BindingMismatch("grant authorization binding mismatch")
        return authorization

    def recheck_grant(
        self,
        intent: LoginIntent,
        initial_grant: GrantAuthorization,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> GrantAuthorization:
        """Resolve the current grant epoch immediately before a Vault read."""
        current_binding = self.resolve_binding(intent, deadline=deadline)
        current_grant = self.resolve_grant(intent, current_binding, deadline=deadline)
        # Keep the initial argument explicit in the API so implementations can
        # compare an atomic lease/epoch; equality is checked by the coordinator.
        _ = initial_grant
        return current_grant

    def validate_intent(
        self,
        intent: LoginIntent,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> BrokerResult | SiteDeclaration:
        """Return a declaration only after validating the server-side binding."""
        try:
            self.resolve_binding(intent, deadline=deadline)
            declaration = self._declarations.get(intent.site_id)
            if declaration is None:
                return BrokerResult(intent.request_id, "unsupported", "site_not_declared")
            return declaration
        except BindingMismatch:
            return BrokerResult(intent.request_id, "failed", "binding_mismatch")
        except StaleBinding:
            return BrokerResult(intent.request_id, "failed", "stale_binding")
        except LookupError as exc:
            error_code = "grant_revoked" if str(exc) == "grant revoked" else "binding_unavailable"
            return BrokerResult(intent.request_id, "not_shared", error_code)
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")

    def request_login(
        self,
        intent: LoginIntent,
        *,
        current_url: str,
        fetch_credentials: Callable[[str], object],
        run_adapter: LoginAdapter[object, object],
    ) -> BrokerResult:
        """Compatibility test-only seam; production HTTP uses ``BrokerCoordinator``.

        This compatibility path remains intentionally unreachable from
        ``BrokerHttpServer.handle``. It still fails closed when production
        authorization dependencies were supplied.
        """
        if self._grant_resolver is None or self._target_preflight is None:
            return self._test_only_request_login(
                intent,
                current_url=current_url,
                fetch_credentials=fetch_credentials,
                run_adapter=run_adapter,
            )
        declaration_or_result = self.validate_intent(intent)
        if isinstance(declaration_or_result, BrokerResult):
            return declaration_or_result
        declaration = declaration_or_result

        try:
            initial_binding = self.resolve_binding(intent)
            if self._target_preflight is None:
                if not declaration.allows(current_url):
                    return BrokerResult(intent.request_id, "failed", "origin_not_allowed")
                initial_target = None
            else:
                initial_target = self.preflight_target(intent, declaration)
            initial_grant = self.resolve_grant(intent, initial_binding)
        except BindingMismatch:
            return BrokerResult(intent.request_id, "failed", "binding_mismatch")
        except StaleBinding:
            return BrokerResult(intent.request_id, "failed", "stale_binding")
        except LookupError as exc:
            code = "grant_revoked" if str(exc) == "grant revoked" else "grant_unavailable"
            return BrokerResult(intent.request_id, "not_shared", code)
        except ValueError:
            return BrokerResult(intent.request_id, "failed", "invalid_target")
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")

        try:
            material = fetch_credentials(initial_grant.username_ref)
        except LookupError:
            return BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")

        try:
            current_binding = self._resolve_binding(intent)
            self.validate_binding(intent, current_binding)
            if self._target_preflight is None:
                if not declaration.allows(current_url):
                    return BrokerResult(intent.request_id, "failed", "origin_not_allowed")
                current_target = None
            else:
                current_target = self.preflight_target(intent, declaration)
            current_grant = self.resolve_grant(intent, current_binding)
            if current_grant != initial_grant:
                return BrokerResult(intent.request_id, "failed", "grant_changed")
            if current_target != initial_target:
                return BrokerResult(intent.request_id, "failed", "target_changed")
        except BindingMismatch:
            return BrokerResult(intent.request_id, "failed", "binding_mismatch")
        except StaleBinding:
            return BrokerResult(intent.request_id, "failed", "stale_binding")
        except LookupError as exc:
            code = "grant_revoked" if str(exc) == "grant revoked" else "binding_unavailable"
            return BrokerResult(intent.request_id, "not_shared", code)
        except ValueError:
            return BrokerResult(intent.request_id, "failed", "invalid_target")
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")

        try:
            outcome = run_adapter(declaration, material)
        except ValueError:
            return BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")
        return self.result_from_adapter(intent.request_id, outcome)

    def _test_only_request_login(
        self,
        intent: LoginIntent,
        *,
        current_url: str,
        fetch_credentials: Callable[[str], object],
        run_adapter: LoginAdapter[object, object],
    ) -> BrokerResult:
        """Exercise historical unit seams without weakening production HTTP."""
        declaration_or_result = self.validate_intent(intent)
        if isinstance(declaration_or_result, BrokerResult):
            return declaration_or_result
        if not declaration_or_result.allows(current_url):
            return BrokerResult(intent.request_id, "failed", "origin_not_allowed")
        if not intent.username_ref:
            return BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
        try:
            material = fetch_credentials(intent.username_ref)
        except LookupError:
            return BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")
        try:
            current_binding = self._resolve_binding(intent)
            self.validate_binding(intent, current_binding)
            if not declaration_or_result.allows(current_url):
                return BrokerResult(intent.request_id, "failed", "origin_not_allowed")
            outcome = run_adapter(declaration_or_result, material)
        except BindingMismatch:
            return BrokerResult(intent.request_id, "failed", "binding_mismatch")
        except StaleBinding:
            return BrokerResult(intent.request_id, "failed", "stale_binding")
        except LookupError as exc:
            code = "grant_revoked" if str(exc) == "grant revoked" else "grant_unavailable"
            return BrokerResult(intent.request_id, "not_shared", code)
        except ValueError:
            return BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        except (BrowserUnavailable, DependencyUnavailable):
            return BrokerResult(intent.request_id, "failed", "browser_unavailable")
        return self.result_from_adapter(intent.request_id, outcome)

    @staticmethod
    def result_from_adapter(request_id: str, outcome: AdapterResult) -> BrokerResult:
        """Convert an internal adapter result to the public status-only result."""
        if outcome.status not in BROKER_STATUS_VALUES:
            return BrokerResult(request_id, "failed", "adapter_result_invalid")
        if outcome.status == "authenticated" and not outcome.identity_verified:
            return BrokerResult(request_id, "failed", outcome.error_code or "identity_unverified")
        return BrokerResult(request_id, outcome.status, outcome.error_code)

    @staticmethod
    def validate_binding(intent: LoginIntent, binding: ResolvedBinding) -> None:
        """Validate caller assertions against one current server-side binding."""
        if binding.revoked:
            raise LookupError("grant revoked")
        if (
            binding.profile_id != intent.profile_id
            or binding.principal_id != intent.principal_id
            or binding.browser_id != intent.browser_id
            or binding.site_id != intent.site_id
        ):
            raise BindingMismatch("intent binding mismatch")
        requested_generation = intent.binding_generation
        if requested_generation is not None and requested_generation != binding.generation:
            raise StaleBinding("binding generation mismatch")

    _validate_binding = validate_binding


__all__ = [
    "AdapterResult",
    "BindingMismatch",
    "BrokerService",
    "GrantResolver",
    "LoginAdapter",
    "ResolvedBinding",
    "StaleBinding",
    "TargetPreflight",
]
