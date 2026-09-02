"""Value objects and bounded errors for the downloads boundary."""

from __future__ import annotations

from dataclasses import dataclass
import re


_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]{0,255}$")


class DownloadsError(ValueError):
    """Base class for bounded downloads contract violations."""


class DownloadNameError(DownloadsError):
    """The supplied name is not a safe flat download name."""


class OwnerMismatch(DownloadsError):
    """The supplied path attempts to escape the server-bound owner area."""


@dataclass(frozen=True)
class ServerIdentity:
    """Non-sensitive identity for one running service instance."""

    component: str
    instance_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.component, str) or not _TOKEN.fullmatch(self.component):
            raise ValueError("component must be bounded non-empty text")
        if not isinstance(self.instance_id, str) or not _TOKEN.fullmatch(self.instance_id):
            raise ValueError("instance_id must be DNS-safe non-empty text")


@dataclass(frozen=True)
class PrincipalIdentity:
    """Server-derived principal and browser binding for one request."""

    request_id: str
    principal_id: str
    profile_id: str
    browser_id: str
    generation: str

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not _REQUEST_ID.fullmatch(self.request_id):
            raise ValueError("request_id must be bounded non-empty text")
        if not isinstance(self.principal_id, str) or not _PRINCIPAL.fullmatch(self.principal_id):
            raise ValueError("principal_id must be bounded non-empty text")
        for field in ("profile_id", "browser_id", "generation"):
            value = getattr(self, field)
            if not isinstance(value, str) or not _TOKEN.fullmatch(value):
                raise ValueError(f"{field} must be bounded non-empty text")


@dataclass(frozen=True)
class DownloadEntry:
    """Bounded metadata for a file or quarantined object."""

    name: str
    size: int
    mtime: int
    owner: str
    quarantined: bool = False
    qname: str | None = None
    sha256: str | None = None

    def public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "size": int(self.size),
            "mtime": int(self.mtime),
            "owner": self.owner,
            "quarantined": self.quarantined,
        }
        if self.qname is not None:
            payload["qname"] = self.qname
        if self.sha256 is not None:
            payload["sha256"] = self.sha256
        return payload


@dataclass(frozen=True)
class DownloadReceipt:
    """Non-sensitive result of an accepted durable ingest."""

    name: str
    size: int
    mtime: int
    sha256: str
    owner: str

    def public_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "size": int(self.size),
            "mtime": int(self.mtime),
            "sha256": self.sha256,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class DownloadRequest:
    """Bounded request input for file operations."""

    name: str
    request_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or len(self.name) > 1024:
            raise ValueError("name must be bounded non-empty text")
        if not isinstance(self.request_id, str) or not _REQUEST_ID.fullmatch(self.request_id):
            raise ValueError("request_id must be bounded non-empty text")


@dataclass(frozen=True)
class DownloadResponse:
    """Bounded listing envelope."""

    principal_id: str
    entries: tuple[DownloadEntry, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "entries": [entry.public_dict() for entry in self.entries],
        }
