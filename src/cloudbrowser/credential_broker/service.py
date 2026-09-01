from dataclasses import dataclass
from typing import Callable, Mapping

from .contracts import BrokerResult, LoginIntent, SiteDeclaration


@dataclass(frozen=True)
class ResolvedBinding:
    """Server-authoritative identity and browser binding for one request."""

    profile_id: str
    principal_id: str
    browser_id: str
    site_id: str
    generation: str


class BindingMismatch(ValueError):
    """Raised when a request assertion differs from server-authoritative state."""


class BrokerService:
    """Validate broker intent and return a bounded status-only result.

    Credential retrieval and browser filling are intentionally not implemented
    here. This first vertical slice establishes the authorization boundary
    before adapter code is extracted.
    """

    def __init__(
        self,
        resolve_binding: Callable[[LoginIntent], ResolvedBinding],
        declarations: Mapping[str, SiteDeclaration],
    ) -> None:
        self._resolve_binding = resolve_binding
        self._declarations = dict(declarations)

    def validate_intent(self, intent: LoginIntent) -> BrokerResult | SiteDeclaration:
        try:
            binding = self._resolve_binding(intent)
            if (
                binding.profile_id != intent.profile_id
                or binding.principal_id != intent.principal_id
                or binding.browser_id != intent.browser_id
                or binding.site_id != intent.site_id
            ):
                raise BindingMismatch("intent binding mismatch")
            declaration = self._declarations.get(intent.site_id)
            if declaration is None:
                return BrokerResult(intent.request_id, "unsupported", "site_not_declared")
            return declaration
        except BindingMismatch:
            return BrokerResult(intent.request_id, "failed", "binding_mismatch")
        except (KeyError, LookupError):
            return BrokerResult(intent.request_id, "not_shared", "binding_unavailable")
