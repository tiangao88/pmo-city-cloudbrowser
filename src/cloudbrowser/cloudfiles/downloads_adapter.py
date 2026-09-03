"""Test-only in-process adapter for the internal downloads service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO

from cloudbrowser.downloads.contracts import PrincipalIdentity
from cloudbrowser.downloads.service import DownloadsService

from .contracts import PrincipalBinding


@dataclass
class DownloadsStoreAdapter:
    """Adapt DownloadsService to the CloudFiles Phase 2 port contract."""

    service: DownloadsService

    @staticmethod
    def _identity(binding: PrincipalBinding) -> PrincipalIdentity:
        return PrincipalIdentity(
            request_id=binding.request_id,
            principal_id=binding.principal_id,
            profile_id=binding.profile_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
        )

    def publish(self, *, binding: PrincipalBinding, source_name: str, source: BinaryIO, size: int, sha256: str):
        """Atomically publish a clean staged stream."""

        return self.service.ingest(self._identity(binding), source_name, source)

    def quarantine(self, *, binding: PrincipalBinding, source_name: str, source: BinaryIO, size: int, sha256: str):
        """Store a non-clean staged stream outside entries."""

        return self.service.quarantine(self._identity(binding), source_name, source)

    def list_files(self, *, binding: PrincipalBinding) -> dict[str, list[dict[str, Any]]]:
        response = self.service.list_files(self._identity(binding))
        return {"entries": [entry.public_dict() for entry in response.entries]}

    def read_file(self, *, binding: PrincipalBinding, name: str) -> bytes | None:
        return self.service.read_file(self._identity(binding), name)


__all__ = ["DownloadsStoreAdapter"]
