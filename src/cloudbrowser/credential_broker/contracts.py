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
    username_ref: str
    target_tab_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class SiteDeclaration:
    """Immutable destination policy used to authorize one broker operation."""

    site_id: str
    origin: str
    redirect_origins: tuple[str, ...] = ()

    def allows(self, url: str) -> bool:
        """Allow only an exact declared origin or an explicit redirect origin."""
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
