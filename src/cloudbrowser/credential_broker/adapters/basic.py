"""HTTP Basic Auth adapter for the credential broker (PRD-BR-04).

Scope (status-only, secret-safe):

- fills the browser's Basic Auth challenge on the exact declared origin;
- permits only declared redirect origins (no wildcard, no subdomain matching);
- refuses to fill over plain HTTP;
- the response is ``authenticated`` only when the browser's challenge was
  resolved on the declared origin; otherwise ``failed`` with a bounded
  ``error_code`` and no fill attempted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..service import AdapterResult


class BasicAuthBrowser(Protocol):
    def current_url(self) -> str: ...

    def has_basic_auth_challenge(self, origin: str) -> bool: ...

    def submit_basic_auth(self, origin: str, username: str, password: str) -> None: ...


@dataclass(frozen=True)
class CredentialMaterial:
    """Broker-owned payload; never serialized into a public response."""

    username: str
    password: str


@dataclass(frozen=True)
class BasicAuthDeclaration:
    site_id: str
    origin: str
    redirect_origins: tuple[str, ...] = ()
    username_ref: str = ""

    def allows(self, current_url: str) -> bool:
        parsed = urlsplit(current_url)
        if parsed.scheme != "https" or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in self._allowed_origins()

    def _allowed_origins(self) -> tuple[str, ...]:
        return (self.origin, *self.redirect_origins)


class BasicAuthAdapter:
    """Execute the bounded HTTP Basic Auth fill on the declared origin."""

    def execute(
        self,
        declaration: BasicAuthDeclaration,
        material: CredentialMaterial,
        browser: BasicAuthBrowser,
    ) -> AdapterResult:
        current_url = browser.current_url()
        parsed_scheme = current_url.split("://", 1)[0] if "://" in current_url else ""
        if parsed_scheme != "https":
            raise ValueError("HTTP Basic Auth fill requires an HTTPS origin")
        if not declaration.allows(current_url):
            raise ValueError("current origin is not in the declared allowlist")
        if not browser.has_basic_auth_challenge(declaration.origin):
            return AdapterResult("failed", False)
        browser.submit_basic_auth(declaration.origin, material.username, material.password)
        return AdapterResult("authenticated", True)
