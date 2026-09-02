from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, TypeVar

from ..security import BROKER_STATUS_VALUES
from .contracts import BrokerResult, LoginIntent, SiteDeclaration


AdapterDeclaration = TypeVar("AdapterDeclaration")
AdapterMaterial = TypeVar("AdapterMaterial")


class LoginAdapter(Protocol[AdapterDeclaration, AdapterMaterial]):
    """Internal adapter contract used by the broker service."""

    def __call__(self, declaration: AdapterDeclaration, material: AdapterMaterial) -> "AdapterResult": ...


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
    ) -> None:
        self._resolve_binding = resolve_binding
        self._declarations = dict(declarations)

    def validate_intent(self, intent: LoginIntent) -> BrokerResult | SiteDeclaration:
        """Return a declaration only after validating the server-side binding."""
        try:
            binding = self._resolve_binding(intent)
            self.validate_binding(intent, binding)
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

    def request_login(
        self,
        intent: LoginIntent,
        *,
        current_url: str,
        fetch_credentials: Callable[[str], object],
        run_adapter: LoginAdapter[object, object],
    ) -> BrokerResult:
        """Run bounded orchestration with broker material kept internal."""
        declaration_or_result = self.validate_intent(intent)
        if isinstance(declaration_or_result, BrokerResult):
            return declaration_or_result
        declaration = declaration_or_result
        if not declaration.allows(current_url):
            return BrokerResult(intent.request_id, "failed", "origin_not_allowed")

        try:
            material = fetch_credentials(intent.username_ref)
        except LookupError:
            return BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
        except Exception:
            return BrokerResult(intent.request_id, "failed", "internal")

        # Re-resolve immediately before the credential-bearing browser call.
        # This prevents a stale material object from being used after a slot,
        # owner, browser, generation, or revocation change.
        try:
            current_binding = self._resolve_binding(intent)
            self.validate_binding(intent, current_binding)
        except BindingMismatch:
            return BrokerResult(intent.request_id, "failed", "binding_mismatch")
        except StaleBinding:
            return BrokerResult(intent.request_id, "failed", "stale_binding")
        except LookupError as exc:
            code = "grant_revoked" if str(exc) == "grant revoked" else "binding_unavailable"
            return BrokerResult(intent.request_id, "not_shared", code)

        try:
            outcome = run_adapter(declaration, material)
        except ValueError:
            return BrokerResult(intent.request_id, "failed", "adapter_invalid_target")
        except Exception:
            return BrokerResult(intent.request_id, "failed", "internal")
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

    # Compatibility for the first internal test slice.
    _validate_binding = validate_binding


__all__ = [
    "AdapterResult",
    "BindingMismatch",
    "BrokerService",
    "LoginAdapter",
    "ResolvedBinding",
    "StaleBinding",
]
