"""Identity and error contracts shared by the downloads boundary."""

from __future__ import annotations

from dataclasses import dataclass
import re


_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,256}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_BROWSER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,256}$")


class DownloadsError(ValueError):
    """Base class for downloads contract violations."""


class DownloadNameError(DownloadsError):
    """Caller supplied a download name that escapes or is unsafe."""


class OwnerMismatch(DownloadsError):
    """Caller attempted to reference data outside their owner scope."""


@dataclass(frozen=True)
class ServerIdentity:
    """Bounded server identity surfaced on health responses."""

    component: str
    instance_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not self.component or len(self.component) > 64:
            raise ValueError("component must be bounded non-empty text")
        if (
            not isinstance(self.instance_id, str)
            or not self.instance_id
            or not _OWNER_PATTERN.fullmatch(self.instance_id)
        ):
            raise ValueError("instance_id must be DNS-safe non-empty text")


@dataclass(frozen=True)
class PrincipalIdentity:
    """Server-derived identity attached to one downloads request."""

    request_id: str
    principal_id: str
    profile_id: str
    browser_id: str
    generation: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not _REQUEST_ID_PATTERN.fullmatch(self.request_id):
            raise ValueError("request_id must be bounded non-empty text")
        if (
            not isinstance(self.principal_id, str)
            or not _OWNER_PATTERN.fullmatch(self.principal_id)
        ):
            raise ValueError("principal_id must be DNS-safe non-empty text")
        for field in ("profile_id", "generation"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(f"{field} must be bounded non-empty text")
        if not isinstance(self.browser_id, str) or not _BROWSER_ID_PATTERN.fullmatch(self.browser_id):
            raise ValueError("browser_id must be bounded non-empty text")


@dataclass(frozen=True)
class DownloadEntry:
    """Bounded metadata describing one durable per-owner file."""

    name: str
    size: int
    mtime: int
    owner: str

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "size": int(self.size),
            "mtime": int(self.mtime),
            "owner": self.owner,
        }


@dataclass(frozen=True)
class DownloadRequest:
    """Caller input accepted by the downloads boundary."""

    name: str
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 1024:
            raise ValueError("name must be bounded non-empty text")
        if not isinstance(self.request_id, str) or not _REQUEST_ID_PATTERN.fullmatch(self.request_id):
            raise ValueError("request_id must be bounded non-empty text")


@dataclass(frozen=True)
class DownloadResponse:
    """Bounded listing returned to the requester."""

    principal_id: str
    entries: tuple[DownloadEntry, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "entries": [entry.public_dict() for entry in self.entries],
        }
