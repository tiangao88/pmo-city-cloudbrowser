"""Bounded HTTP Basic Auth adapter for the credential broker.

The adapter uses only a broker-side browser capability. It never constructs a
URL containing credentials, forwards credentials to an undeclared origin, or
returns credential material. The browser double may expose either the current
challenge as ``challenge_origin()`` or the older boolean
``has_basic_auth_challenge(origin)`` capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..service import AdapterResult
from .form import CredentialMaterial


class BasicAuthBrowser(Protocol):
    def current_url(self, *, target_id: str) -> str: ...

    def submit_basic_auth(
        self,
        origin: str,
        username: str,
        password: str,
        *,
        target_id: str,
        success_path: str,
    ) -> None: ...


@dataclass(frozen=True)
class BasicAuthDeclaration:
    site_id: str
    origin: str
    redirect_origins: tuple[str, ...] = ()
    username_ref: str = ""
    success_path: str = ""

    def __post_init__(self) -> None:
        if _https_origin(self.origin) != self.origin:
            raise ValueError("Basic Auth origin must be an exact HTTPS origin")
        if not self.success_path:
            return
        if not self.success_path.startswith("/") or self.success_path.startswith("//"):
            raise ValueError("Basic Auth success_path must be an absolute path")
        if "?" in self.success_path or "#" in self.success_path:
            raise ValueError("Basic Auth success_path must not contain query or fragment")

    def allows(self, current_url: str) -> bool:
        current = _https_origin(current_url)
        return current is not None and current in self._allowed_origins()

    def _allowed_origins(self) -> tuple[str, ...]:
        return (self.origin, *self.redirect_origins)


class BasicAuthAdapter:
    """Answer one exact-origin browser Basic Auth challenge."""

    def execute(
        self,
        declaration: BasicAuthDeclaration,
        material: CredentialMaterial,
        browser: BasicAuthBrowser,
        *,
        target_id: str,
    ) -> AdapterResult:
        if not target_id:
            return AdapterResult("failed", False, "target_missing")
        if not declaration.success_path:
            return AdapterResult("failed", False, "success_proof_missing")
        current_url = browser.current_url(target_id=target_id)
        current_origin = _https_origin(current_url)
        if current_origin is None:
            raise ValueError("HTTP Basic Auth fill requires an HTTPS origin")
        if not declaration.allows(current_url):
            raise ValueError("current origin is not in the declared allowlist")
        if not _challenge_present(browser, declaration.origin, target_id=target_id):
            return AdapterResult("failed", False, "challenge_missing")

        # The only credential-bearing call is the narrow browser capability.
        browser.submit_basic_auth(
            declaration.origin,
            material.username,
            material.password,
            target_id=target_id,
            success_path=declaration.success_path,
        )

        after_origin = _https_origin(browser.current_url(target_id=target_id))
        if after_origin is None or after_origin not in declaration._allowed_origins():
            return AdapterResult("failed", False, "origin_changed")

        # A capability exposing the challenge after navigation lets us stop
        # on a repeated challenge before claiming success.
        challenge_probe = getattr(browser, "challenge_origin", None)
        if callable(challenge_probe):
            if challenge_probe(target_id=target_id) == declaration.origin:
                return AdapterResult("failed", False, "challenge_loop")

        application_proof = getattr(browser, "application_authenticated", None)
        if not callable(application_proof) or not bool(
            application_proof(target_id=target_id)
        ):
            return AdapterResult("failed", False, "success_unverified")
        return AdapterResult("authenticated", True)


def _https_origin(url: str) -> str | None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    # urlsplit().netloc retains an explicit port, so the declaration remains
    # exact and cannot silently widen to another service on the host.
    return f"https://{parsed.netloc}"


def _challenge_present(browser: BasicAuthBrowser, origin: str, *, target_id: str) -> bool:
    challenge_origin = getattr(browser, "challenge_origin", None)
    if callable(challenge_origin):
        return challenge_origin(target_id=target_id) == origin
    challenge_probe = getattr(browser, "has_basic_auth_challenge", None)
    if callable(challenge_probe):
        return bool(challenge_probe(origin, target_id=target_id))
    return False


__all__ = ["BasicAuthAdapter", "BasicAuthBrowser", "BasicAuthDeclaration", "CredentialMaterial"]
