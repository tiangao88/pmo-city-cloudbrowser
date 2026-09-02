"""Broker-owned RFC 6238 TOTP adapter.

Only the seed-bearing broker process constructs ``TOTPMaterial``. The adapter
computes a code in memory, fills the declared MFA field, and returns only a
bounded status. No network, logging, code persistence, or drift guessing is
performed here.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from ..service import AdapterResult


class TOTPBrowser(Protocol):
    def current_url(self) -> str: ...

    def has_selector(self, selector: str) -> bool: ...

    def fill_code(self, selector: str, value: str) -> None: ...

    def click(self, selector: str) -> None: ...


@dataclass(frozen=True)
class TOTPDeclaration:
    site_id: str
    origin: str
    code_selector: str
    submit_selector: str
    redirect_origins: tuple[str, ...] = ()

    def allows(self, current_url: str) -> bool:
        parsed = urlsplit(current_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        origin = f"https://{parsed.netloc}"
        return origin in (self.origin, *self.redirect_origins)


@dataclass(frozen=True)
class TOTPMaterial:
    # This value is intentionally broker-internal and has no public serializer.
    secret: bytes
    digits: int = 6
    period: int = 30
    algorithm: str = "sha1"

    def __post_init__(self) -> None:
        if not isinstance(self.secret, bytes) or not self.secret:
            raise ValueError("TOTP secret must be non-empty broker material")
        if self.digits != 6:
            raise ValueError("only the RFC 6238 6-digit default is exposed in this release")
        if self.period <= 0:
            raise ValueError("TOTP period must be positive")
        if self.algorithm != "sha1":
            raise ValueError("only RFC 6238 SHA-1 is supported in this release")


class TOTPAdapter:
    """Compute and submit one RFC 6238 code on an allowlisted MFA stage."""

    def execute(
        self,
        declaration: TOTPDeclaration,
        material: TOTPMaterial,
        browser: TOTPBrowser,
        now: float | None = None,
    ) -> AdapterResult:
        if not declaration.allows(browser.current_url()):
            return AdapterResult("failed", False, "invalid_target")
        if not browser.has_selector(declaration.code_selector) or not browser.has_selector(
            declaration.submit_selector
        ):
            return AdapterResult("failed", False, "mfa_controls_missing")
        timestamp = int(now if now is not None else time.time())
        code = compute_totp(material.secret, timestamp, period=material.period, digits=material.digits)
        browser.fill_code(declaration.code_selector, code)
        browser.click(declaration.submit_selector)

        application_proof = getattr(browser, "application_authenticated", None)
        if callable(application_proof) and not bool(application_proof()):
            return AdapterResult("failed", False, "success_unverified")
        return AdapterResult("authenticated", True)


def compute_totp(secret: bytes, timestamp: int, *, period: int = 30, digits: int = 6) -> str:
    """Return the RFC 6238 SHA-1 code for an explicit timestamp."""
    if not isinstance(secret, bytes) or not secret:
        raise ValueError("TOTP secret must be non-empty broker material")
    if period <= 0 or digits != 6:
        raise ValueError("unsupported TOTP parameters")
    counter = int(timestamp) // period
    message = struct.pack(">Q", counter)
    digest = hmac.new(secret, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


# Internal compatibility name used by the first broker slice.
_compute_totp = compute_totp

__all__ = ["TOTPAdapter", "TOTPBrowser", "TOTPDeclaration", "TOTPMaterial", "compute_totp"]
