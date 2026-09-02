"""Owner-bound downloads service contract."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .contracts import (
    DownloadEntry,
    DownloadNameError,
    DownloadRequest,
    DownloadResponse,
    OwnerMismatch,
    PrincipalIdentity,
)
from .store import DownloadStore, safe_name


class DownloadsService:
    """Resolve one bounded owner area per server-derived identity."""

    def __init__(self, *, store_root: Path) -> None:
        self._store = DownloadStore(Path(store_root))

    def list_files(self, identity: PrincipalIdentity) -> DownloadResponse:
        """Return bounded metadata for the requesting owner's area."""

        entries = tuple(self._store.list_entries(identity.principal_id))
        return DownloadResponse(
            principal_id=identity.principal_id,
            entries=entries,
        )

    def read_file(self, identity: PrincipalIdentity, name: str) -> bytes | None:
        """Return the bounded file bytes for the requester's area."""

        DownloadRequest(name=name, request_id=identity.request_id)
        if not isinstance(name, str) or not name:
            raise DownloadNameError("name must be non-empty text")
        # Path separators and absolute paths are owner-escape attempts.
        if "/" in name or "\\" in name or name.startswith("/"):
            raise OwnerMismatch("cross-owner paths are rejected")
        if ".." in Path(name).parts:
            raise OwnerMismatch("path traversal is rejected")
        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        return self._store.read(identity.principal_id, safe)


__all__ = [
    "DownloadsService",
    "DownloadEntry",
    "DownloadNameError",
    "DownloadRequest",
    "DownloadResponse",
    "OwnerMismatch",
    "PrincipalIdentity",
    "safe_name",
]


def health_metadata(*, identity: PrincipalIdentity | None = None) -> Mapping[str, str]:
    """Return bounded health metadata for the downloads service."""

    return {
        "status": "ok",
        "component": "downloads",
    }
