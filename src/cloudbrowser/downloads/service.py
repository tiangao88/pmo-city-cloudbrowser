"""Owner-bound downloads service contract."""

from __future__ import annotations

from datetime import datetime, timezone
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

    def __init__(self, *, store_root: Path, quota_bytes: int | None = None) -> None:
        if quota_bytes is None:
            self._store = DownloadStore(Path(store_root))
        else:
            self._store = DownloadStore(Path(store_root), quota_bytes=quota_bytes)

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

    # ------------------------------------------------------------------
    # Operational lifecycle (Phase 4): quota, retention purge, erasure
    # ------------------------------------------------------------------

    def usage_bytes(self, principal_id: str) -> int:
        """Return the retrievable bytes stored for one principal."""

        return self._store.usage_bytes(principal_id)

    def purge_expired(
        self, principal_id: str, *, older_than: datetime | None = None
    ) -> list[str]:
        """Purge retrievable entries older than the retention cutoff.

        The default cutoff is 90 days before the current UTC time. Returns
        the removed safe names for a redacted audit summary.
        """

        moment = older_than or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return self._store.purge(principal_id, older_than_ts=moment.timestamp())

    def erase(self, principal_id: str) -> None:
        """Erase every durable reference to a principal (idempotent)."""

        self._store.erase(principal_id)


__all__ = ["DownloadsService"]
