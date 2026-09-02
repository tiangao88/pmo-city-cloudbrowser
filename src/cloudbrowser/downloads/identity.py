"""Identity helpers for the downloads service."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
import secrets
from typing import Mapping

from .contracts import ServerIdentity


@dataclass(frozen=True)
class TrustedSecret:
    """Bounded shared secret used to authenticate trusted-router requests."""

    value: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.value, bytes) or len(self.value) < 16:
            raise ValueError("shared secret must be at least 16 bytes")


def check_trusted_secret(
    *,
    provided: Mapping[str, str] | None,
    expected: TrustedSecret,
    header: str = "X-CB-Trusted-Secret",
) -> bool:
    """Return True when the request header matches the server-owned secret."""

    if provided is None:
        return False
    raw = None
    target = header.lower()
    for key, value in provided.items():
        if key.lower() == target:
            raw = value
            break
    if not isinstance(raw, str) or not raw:
        return False
    return hmac.compare_digest(raw.encode("utf-8"), expected.value)


def constant_time_equals(a: str, b: str) -> bool:
    """Compatibility helper for stdlib-only deployments."""

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_trusted_secret() -> bytes:
    """Generate a high-entropy shared secret (development use only)."""

    return secrets.token_bytes(32)


__all__ = [
    "ServerIdentity",
    "TrustedSecret",
    "check_trusted_secret",
    "constant_time_equals",
    "generate_trusted_secret",
]
