"""Intent/result contracts for the credential broker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from ..security import BROKER_STATUS_VALUES


@dataclass(frozen=True)
class LoginIntent:
    """Caller-visible login intent; it carries no credential material."""

    request_id: str
    profile_id: str
    principal_id: str
    browser_id: str
    site_id: str
    # Deprecated transport assertion. Authorization must use GrantResolver;
    # callers cannot select a vault item by supplying this value.
    username_ref: str = ""
    target_tab_id: str | None = None
    idempotency_key: str | None = None
    binding_generation: str | None = None


class AuthorizationChanged(LookupError):
    """The grant authorization epoch changed before the gated side effect."""

    def __init__(self, message: str = "grant changed") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class GrantAuthorization:
    """Server-owned grant item authorization for one exact live binding.

    ``username_ref`` is resolved by the broker authorization seam, never copied
    from a caller request. Every binding field is mandatory so an authorization
    cannot silently become a partial wildcard.
    """

    username_ref: str
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str
    site_id: str
    target_tab_id: str
    # Durable grant authorization epoch. Every authorization carries a positive
    # epoch; a changed epoch is a changed grant even when all scope fields match.
    epoch: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int) or self.epoch <= 0:
            raise ValueError("epoch must be a non-negative integer")
        for name in (
            "username_ref",
            "profile_id",
            "principal_id",
            "browser_id",
            "generation",
            "site_id",
            "target_tab_id",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or len(value.encode("utf-8")) > 256
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            ):
                raise ValueError(f"{name} must be bounded non-empty text")

    def matches(self, binding: object, site_id: str, target_tab_id: str) -> bool:
        """Return whether this authorization names the complete live scope."""
        return (
            getattr(binding, "profile_id", None) == self.profile_id
            and getattr(binding, "principal_id", None) == self.principal_id
            and getattr(binding, "browser_id", None) == self.browser_id
            and getattr(binding, "generation", None) == self.generation
            and getattr(binding, "site_id", None) == self.site_id == site_id
            and self.target_tab_id == target_tab_id
        )


@dataclass(frozen=True)
class SiteDeclaration:
    """Immutable destination policy used to authorize one broker operation."""

    site_id: str
    origin: str
    redirect_origins: tuple[str, ...] = ()

    def allows(self, url: str) -> bool:
        """Allow only an exact declared or explicitly redirected origin."""
        candidate = urlsplit(url)
        if not candidate.scheme or not candidate.netloc:
            return False
        origin = f"{candidate.scheme}://{candidate.netloc}"
        return origin in (self.origin, *self.redirect_origins)


@dataclass(frozen=True)
class BrokerResult:
    """Status-only result safe to return to the agent."""

    request_id: str
    status: str
    error_code: str | None = None
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if self.status not in BROKER_STATUS_VALUES:
            raise ValueError("invalid broker status")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        if self.error_code is not None and (not self.error_code or len(self.error_code) > 64):
            raise ValueError("error_code must be bounded")

    def to_public_dict(self) -> Mapping[str, str | int | None]:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
        }
