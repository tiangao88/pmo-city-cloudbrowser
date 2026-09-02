"""Generic, deterministic SSO adapter contract.

This module deliberately does not implement an Authentik/TinyAuth daemon,
network capture, cookie copying, or provider-specific selectors. It enforces
the generic policy: declared IdP/callback/application origins, dual identity
proof, and fail-closed MFA handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..service import AdapterResult
from .form import CredentialMaterial


class SSOBrowser(Protocol):
    def current_url(self) -> str: ...

    def begin_login(self, origin: str, username: str, password: str) -> None: ...

    def idp_authenticated(self) -> bool: ...

    def application_identity(self) -> str | None: ...


@dataclass(frozen=True)
class SSODeclaration:
    site_id: str
    idp_origins: tuple[str, ...]
    callback_origins: tuple[str, ...]
    application_origins: tuple[str, ...]
    login_path: str = "/"
    adapter_version: str = "sso/v1"
    allowed_mfa: tuple[str, ...] = ("totp", "human_handoff")

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return (*self.idp_origins, *self.callback_origins, *self.application_origins)

    def allows(self, url: str) -> bool:
        origin = _https_origin(url)
        return origin is not None and origin in self.allowed_origins

    def allows_idp(self, url: str) -> bool:
        origin = _https_origin(url)
        return origin is not None and origin in self.idp_origins

    def allows_application(self, url: str) -> bool:
        origin = _https_origin(url)
        return origin is not None and origin in (*self.callback_origins, *self.application_origins)


class SSOAdapter:
    """Execute only the provider-neutral SSO portion of one login intent."""

    def execute(
        self,
        declaration: SSODeclaration,
        material: CredentialMaterial,
        browser: SSOBrowser,
        *,
        expected_account: str,
    ) -> AdapterResult:
        current_url = browser.current_url()
        if not declaration.allows(current_url):
            return AdapterResult("failed", False, "invalid_target")

        challenge = _mfa_challenge(browser)
        if challenge is not None and challenge not in declaration.allowed_mfa:
            return AdapterResult("unsupported", False, "mfa_unsupported")
        if challenge is not None:
            return AdapterResult("mfa_required", False, "mfa_required")

        if not browser.idp_authenticated():
            # Credentials are sent only through the browser capability and only
            # to the first declared IdP origin. The current URL may be a
            # callback during a reconnect, but it cannot authorize another IdP.
            idp_origin = declaration.idp_origins[0] if declaration.idp_origins else ""
            if not _declared_https_origin(idp_origin):
                return AdapterResult("failed", False, "invalid_target")
            browser.begin_login(idp_origin, material.username, material.password)
            if not browser.idp_authenticated():
                return AdapterResult("failed", False, "credential_rejected")

            challenge = _mfa_challenge(browser)
            if challenge is not None and challenge not in declaration.allowed_mfa:
                return AdapterResult("unsupported", False, "mfa_unsupported")
            if challenge is not None:
                return AdapterResult("mfa_required", False, "mfa_required")

        # An IdP success page or a changed URL is not application success.
        if not declaration.allows_application(browser.current_url()):
            return AdapterResult("failed", False, "success_unverified")
        account = browser.application_identity()
        if not account:
            return AdapterResult("failed", False, "success_unverified")
        if account != expected_account:
            return AdapterResult("failed", False, "identity_mismatch")
        return AdapterResult("authenticated", True)


def _mfa_challenge(browser: SSOBrowser) -> str | None:
    probe = getattr(browser, "mfa_challenge", None)
    if not callable(probe):
        return None
    value = probe()
    return value if isinstance(value, str) and value else None


def _declared_https_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.netloc == parsed.hostname
    )


def _https_origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        return None
    return f"https://{parsed.netloc}"


__all__ = ["SSOAdapter", "SSOBrowser", "SSODeclaration"]
