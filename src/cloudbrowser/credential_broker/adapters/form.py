from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..service import AdapterResult


class FormBrowser(Protocol):
    def current_url(self) -> str: ...

    def fill(self, selector: str, value: str) -> None: ...

    def click(self, selector: str) -> None: ...

    def has_selector(self, selector: str) -> bool: ...

    def read_text(self, selector: str) -> str: ...


@dataclass(frozen=True)
class CredentialMaterial:
    """Short-lived broker-owned material; never serialized to public output."""

    username: str
    password: str


@dataclass(frozen=True)
class FormLoginDeclaration:
    """Bounded selector policy for one ordinary form-login origin."""

    site_id: str
    origin: str
    username_selector: str
    password_selector: str
    submit_selector: str
    success_selector: str
    failure_selectors: tuple[str, ...] = ()
    account_selector: str | None = None
    mfa_selector: str | None = None

    def allows(self, url: str) -> bool:
        parsed = urlsplit(url)
        return bool(parsed.scheme and parsed.netloc and f"{parsed.scheme}://{parsed.netloc}" == self.origin)


class FormLoginAdapter:
    """Execute an allowlisted form login through a narrow browser protocol."""

    def execute(
        self,
        declaration: FormLoginDeclaration,
        material: CredentialMaterial,
        browser: FormBrowser,
    ) -> AdapterResult:
        """Fill exactly declared fields, then return only a bounded result."""
        if not declaration.allows(browser.current_url()):
            return AdapterResult("failed", False)
        if declaration.mfa_selector and browser.has_selector(declaration.mfa_selector):
            return AdapterResult("mfa_required", False)
        controls = (
            declaration.username_selector,
            declaration.password_selector,
            declaration.submit_selector,
        )
        if any(not selector or not browser.has_selector(selector) for selector in controls):
            return AdapterResult("failed", False)
        browser.fill(declaration.username_selector, material.username)
        browser.fill(declaration.password_selector, material.password)
        browser.click(declaration.submit_selector)
        if any(browser.has_selector(selector) for selector in declaration.failure_selectors):
            return AdapterResult("failed", False)
        if not browser.has_selector(declaration.success_selector):
            return AdapterResult("failed", False)
        if declaration.account_selector:
            if browser.read_text(declaration.account_selector) != material.username:
                return AdapterResult("failed", False)
        return AdapterResult("authenticated", True)
