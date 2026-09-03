"""Owner-bound downloads service contract."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from .contracts import (
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
        return DownloadResponse(principal_id=identity.principal_id, entries=entries)

    def read_file(self, identity: PrincipalIdentity, name: str) -> bytes | None:
        """Return bounded file bytes for the requester's area."""

        DownloadRequest(name=name, request_id=identity.request_id)
        if "/" in name or "\\" in name or name.startswith("/") or ".." in Path(name).parts:
            raise OwnerMismatch("cross-owner paths are rejected")
        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        return self._store.read(identity.principal_id, safe)

    def ingest(self, identity: PrincipalIdentity, name: str, source: BinaryIO):
        """Atomically ingest a stream into the server-derived owner area."""

        return self._store.ingest(identity.principal_id, name, source)

    def quarantine(self, identity: PrincipalIdentity, name: str, source: BinaryIO):
        """Retain a non-clean stream outside the retrievable namespace."""

        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        return self._store.quarantine(identity.principal_id, safe, source)


__all__ = ["DownloadsService"]
