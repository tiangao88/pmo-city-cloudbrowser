"""TOTP adapter for the credential broker (PRD-BR-06).

The seed remains broker-only. The derived one-time code is filled into the
declared selector and never recorded. RFC 6238 with SHA-1, 30-second window,
6 digits, no drift compensation in the public surface.
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
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in (self.origin, *self.redirect_origins)


@dataclass(frozen=True)
class TOTPMaterial:
    secret: bytes
    digits: int = 6
    period: int = 30
    algorithm: str = "sha1"

    def __post_init__(self) -> None:
        if self.digits != 6:
            raise ValueError("only the RFC 6238 6-digit default is exposed in this release")
        if self.period <= 0:
            raise ValueError("TOTP period must be positive")
        if self.algorithm != "sha1":
            raise ValueError("only RFC 6238 SHA-1 is supported in this release")


class TOTPAdapter:
    """Compute and submit RFC 6238 TOTP without exposing the seed or code."""

    def execute(
        self,
        declaration: TOTPDeclaration,
        material: TOTPMaterial,
        browser: TOTPBrowser,
        now: float | None = None,
    ) -> AdapterResult:
        if not declaration.allows(browser.current_url()):
            return AdapterResult("failed", False)
        if not browser.has_selector(declaration.code_selector) or not browser.has_selector(
            declaration.submit_selector
        ):
            return AdapterResult("failed", False)
        timestamp = int(now if now is not None else time.time())
        code = _compute_totp(material.secret, timestamp, period=material.period, digits=material.digits)
        browser.fill_code(declaration.code_selector, code)
        browser.click(declaration.submit_selector)
        return AdapterResult("authenticated", True)


def _compute_totp(secret: bytes, timestamp: int, *, period: int, digits: int) -> str:
    counter = timestamp // period
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return str(code_int).zfill(digits)
