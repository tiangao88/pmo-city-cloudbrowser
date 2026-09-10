"""Provider-neutral Authentik SSO adapter with an explicit MFA checkpoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ...security.policy import canonical_identity
from ..deadline import BrokerDeadline, invoke_with_deadline
from ..service import AdapterResult
from .form import CredentialMaterial

_MAX_STAGE_TIMEOUT_S = 30.0


class AuthentikBrowser(Protocol):
    def current_url(self) -> str: ...
    def begin_authentik(self, entry_url: str) -> None: ...
    def identification(self, username: str, password: str) -> str: ...
    def application_identity(self) -> str | None: ...
    def mfa_stage(self) -> str | None: ...


@dataclass(frozen=True)
class AuthentikSSODeclaration:
    site_id: str
    entry_url: str
    idp_origins: tuple[str, ...]
    callback_origins: tuple[str, ...]
    application_origins: tuple[str, ...]
    application_success_paths: tuple[str, ...]
    allowed_mfa: tuple[str, ...] = ("totp",)
    stage_timeout_s: float = 30.0
    application_identity_selector: str = ""
    application_identity_claim: str = ""

    def __post_init__(self) -> None:
        for origin in (*self.idp_origins, *self.callback_origins, *self.application_origins):
            if _https_origin(origin) != origin:
                raise ValueError("SSO origins must be exact HTTPS origins")
        entry = urlsplit(self.entry_url)
        if entry.scheme != "https" or not entry.netloc or entry.username or entry.password:
            raise ValueError("entry_url must be an HTTPS URL")
        if not self.application_success_paths or any(
            not path.startswith("/") or "?" in path or "#" in path
            for path in self.application_success_paths
        ):
            raise ValueError("application success paths are invalid")
        if (
            isinstance(self.stage_timeout_s, bool)
            or not isinstance(self.stage_timeout_s, (int, float))
            or self.stage_timeout_s <= 0
            or self.stage_timeout_s > _MAX_STAGE_TIMEOUT_S
        ):
            raise ValueError("stage_timeout_s is invalid")
        if not self.application_identity_selector and not self.application_identity_claim:
            return
        if not self.application_identity_selector or not self.application_identity_claim:
            raise ValueError("application identity proof rule is required")
        from cloudbrowser.browser_slots.page_actions import _validate_selector

        _validate_selector(self.application_identity_selector)
        claim = self.application_identity_claim or ""
        if not claim.startswith("attribute:"):
            raise ValueError("application identity claim is invalid")
        attribute = claim.removeprefix("attribute:")
        if (
            not attribute
            or len(attribute.encode("utf-8")) > 128
            or not attribute.replace("-", "").replace("_", "").isalnum()
            or attribute.lower().startswith("on")
        ):
            raise ValueError("application identity claim is invalid")

    def allows_idp(self, url: str) -> bool:
        origin = _https_origin(url)
        return origin is not None and origin in self.idp_origins

    def allows_application(self, url: str) -> bool:
        parsed = urlsplit(url)
        origin = _https_origin(url)
        return (
            origin is not None
            and origin in (*self.callback_origins, *self.application_origins)
            and parsed.path in self.application_success_paths
        )

    def allows(self, url: str) -> bool:
        """Preflight permits the declared IdP or exact application success URL."""
        return self.allows_idp(url) or self.allows_application(url)


class AuthentikSSOAdapter:
    """Fill Authentik identification, then stop at human MFA."""

    def execute(
        self,
        declaration: AuthentikSSODeclaration,
        material: CredentialMaterial,
        browser: AuthentikBrowser,
        *,
        deadline: BrokerDeadline | None = None,
        expected_account: str,
    ) -> AdapterResult:
        if deadline is not None:
            deadline.check()
        current = invoke_with_deadline(browser.current_url, deadline=deadline)
        if not declaration.allows_idp(current) and not declaration.allows_application(current):
            invoke_with_deadline(
                browser.begin_authentik,
                declaration.entry_url,
                deadline=deadline,
            )
            current = invoke_with_deadline(browser.current_url, deadline=deadline)
        if not declaration.allows_idp(current) and not declaration.allows_application(current):
            return AdapterResult("failed", False, "invalid_target")
        stage = invoke_with_deadline(browser.mfa_stage, deadline=deadline)
        if stage is not None:
            return _stage_result(stage, declaration.allowed_mfa)
        if declaration.allows_idp(current):
            if deadline is not None:
                deadline.check()
            outcome = invoke_with_deadline(
                browser.identification,
                material.username,
                material.password,
                deadline=deadline,
            )
            if outcome == "rejected":
                return AdapterResult("failed", False, "credential_rejected")
            if outcome not in {"accepted", "submitted"}:
                return AdapterResult("failed", False, "authentik_denied")
            # The browser capability owns bounded transition polling. Do not
            # start a second independent poll/deadline in the broker adapter.
            stage = invoke_with_deadline(browser.mfa_stage, deadline=deadline)
            if stage is not None:
                return _stage_result(stage, declaration.allowed_mfa)
        final_url = invoke_with_deadline(browser.current_url, deadline=deadline)
        if not declaration.allows_application(final_url):
            return AdapterResult("failed", False, "success_unverified")
        account = invoke_with_deadline(browser.application_identity, deadline=deadline)
        if account is None:
            return AdapterResult("failed", False, "success_unverified")
        if canonical_identity(account) is None:
            return AdapterResult("failed", False, "identity_invalid")
        expected = canonical_identity(expected_account)
        observed = canonical_identity(account)
        if expected is None or observed is None:
            return AdapterResult("failed", False, "identity_invalid")
        if observed != expected:
            return AdapterResult("failed", False, "identity_mismatch")
        return AdapterResult("authenticated", True)


def _stage_result(stage: str, allowed: tuple[str, ...]) -> AdapterResult:
    return (
        AdapterResult("mfa_required", False, "mfa_required")
        if stage in allowed
        else AdapterResult("unsupported", False, "mfa_unsupported")
    )


def _https_origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return f"https://{parsed.netloc}"


class SSOAdapter:
    """Compatibility implementation of the generic SSO contract."""

    def execute(self, declaration, material, browser, *, expected_account: str) -> AdapterResult:
        current_url = browser.current_url()
        if not declaration.allows(current_url):
            return AdapterResult("failed", False, "invalid_target")
        challenge = _compat_mfa(browser)
        if challenge is not None:
            return _stage_result(challenge, declaration.allowed_mfa)
        if not browser.idp_authenticated():
            idp_origin = declaration.idp_origins[0] if declaration.idp_origins else ""
            if _https_origin(idp_origin) != idp_origin:
                return AdapterResult("failed", False, "invalid_target")
            browser.begin_login(idp_origin, material.username, material.password)
            if not browser.idp_authenticated():
                return AdapterResult("failed", False, "credential_rejected")
            challenge = _compat_mfa(browser)
            if challenge is not None:
                return _stage_result(challenge, declaration.allowed_mfa)
        if not declaration.allows_application(browser.current_url()):
            return AdapterResult("failed", False, "success_unverified")
        account = browser.application_identity()
        if account is None:
            return AdapterResult("failed", False, "success_unverified")
        if canonical_identity(account) is None:
            return AdapterResult("failed", False, "identity_invalid")
        expected = canonical_identity(expected_account)
        observed = canonical_identity(account)
        if expected is None or observed is None:
            return AdapterResult("failed", False, "identity_invalid")
        if observed != expected:
            return AdapterResult("failed", False, "identity_mismatch")
        return AdapterResult("authenticated", True)


def _compat_mfa(browser) -> str | None:
    probe = getattr(browser, "mfa_challenge", None)
    if not callable(probe):
        return None
    value = probe()
    return value if isinstance(value, str) and value else None


# Backward-compatible generic names remain for existing contract users.
SSOBrowser = AuthentikBrowser


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


__all__ = [
    "AuthentikBrowser",
    "AuthentikSSOAdapter",
    "AuthentikSSODeclaration",
    "SSOAdapter",
    "SSOBrowser",
    "SSODeclaration",
]
