from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, TypeVar

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
    """Internal adapter outcome; identity verification is explicit."""

    status: str
    identity_verified: bool


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
            self._validate_binding(intent, binding)
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
        """Run bounded orchestration with credential material kept internal."""
        declaration_or_result = self.validate_intent(intent)
        if isinstance(declaration_or_result, BrokerResult):
            return declaration_or_result
        declaration = declaration_or_result
        if not declaration.allows(current_url):
            return BrokerResult(intent.request_id, "failed", "origin_not_allowed")
        try:
            material = fetch_credentials(intent.username_ref)
            outcome = run_adapter(declaration, material)
        except LookupError:
            return BrokerResult(intent.request_id, "not_shared", "grant_unavailable")
        if outcome.status not in {"authenticated", "mfa_required", "failed", "unsupported"}:
            return BrokerResult(intent.request_id, "failed", "adapter_result_invalid")
        if outcome.status == "authenticated" and not outcome.identity_verified:
            return BrokerResult(intent.request_id, "failed", "identity_unverified")
        return BrokerResult(intent.request_id, outcome.status)

    @staticmethod
    def _validate_binding(intent: LoginIntent, binding: ResolvedBinding) -> None:
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
