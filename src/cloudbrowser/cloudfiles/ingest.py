"""Phase-2 ingest ports, scanner orchestration, and durable publication."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
from typing import BinaryIO, Protocol

from .contracts import CloudFilesError, PrincipalBinding, TooLarge
from .filenames import require_name


class IngestReceiptError(CloudFilesError):
    """The internal downloads port returned an invalid receipt."""


@dataclass(frozen=True)
class IngestReceipt:
    """Non-sensitive result of one browser-download ingest."""

    name: str
    size: int
    status: str
    request_id: str
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.name or self.status not in {"published", "quarantined"}:
            raise ValueError("invalid ingest receipt")
        if not self.request_id:
            raise ValueError("request_id is required")


class Scanner(Protocol):
    """Scan a temporary file without receiving owner-selected paths."""

    def scan(self, path: Path, *, request_id: str) -> str:
        """Return ``clean`` or a non-clean result such as ``infected``."""


class QuarantineNotifier(Protocol):
    """Bounded quarantine notification seam (threat T14)."""

    def notify_quarantine(self, *, event: dict[str, object]) -> None:
        """Deliver a redacted quarantine event. Never raises into ingest."""


class DownloadsPort(Protocol):
    """Typed internal downloads publication port."""

    def publish(
        self,
        *,
        binding: PrincipalBinding,
        source_name: str,
        source: BinaryIO,
        size: int,
        sha256: str,
    ):
        """Publish a clean staged stream under the server-derived owner."""

    def quarantine(
        self,
        *,
        binding: PrincipalBinding,
        source_name: str,
        source: BinaryIO,
        size: int,
        sha256: str,
    ):
        """Retain a non-clean staged stream outside the retrievable namespace."""


@dataclass
class IngestPipeline:
    """Bounded, scan-before-publish browser completion pipeline."""

    downloads: DownloadsPort
    scanner: Scanner
    temp_root: Path
    max_bytes: int = 1024 * 1024 * 1024
    chunk_bytes: int = 64 * 1024
    notifier: QuarantineNotifier | None = None

    def __post_init__(self) -> None:
        self.temp_root = Path(self.temp_root)
        if self.max_bytes <= 0 or self.chunk_bytes <= 0:
            raise ValueError("ingest limits must be positive")

    def ingest(
        self,
        *,
        binding: PrincipalBinding,
        source_name: str,
        source: BinaryIO,
    ) -> IngestReceipt:
        """Stage, scan, and publish one owner-bound browser completion."""

        safe_name = require_name(source_name)
        if not hasattr(source, "read"):
            raise TypeError("source must be a binary stream")
        self.temp_root.mkdir(parents=True, exist_ok=True)
        temp = self.temp_root / f".cloudfiles-{secrets.token_hex(16)}.tmp"
        size = 0
        digest = hashlib.sha256()
        try:
            old_umask = os.umask(0o077)
            try:
                descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            finally:
                os.umask(old_umask)
            try:
                with os.fdopen(descriptor, "wb", buffering=0) as target:
                    descriptor = -1
                    while True:
                        chunk = source.read(self.chunk_bytes)
                        if not isinstance(chunk, (bytes, bytearray)):
                            raise TypeError("source must yield bytes")
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise TooLarge("ingest exceeds size limit")
                        digest.update(chunk)
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            scan_result = self.scanner.scan(temp, request_id=binding.request_id)
            with temp.open("rb") as staged:
                if scan_result == "clean":
                    receipt = self.downloads.publish(
                        binding=binding,
                        source_name=safe_name,
                        source=staged,
                        size=size,
                        sha256=digest.hexdigest(),
                    )
                    status = "published"
                else:
                    receipt = self.downloads.quarantine(
                        binding=binding,
                        source_name=safe_name,
                        source=staged,
                        size=size,
                        sha256=digest.hexdigest(),
                    )
                    status = "quarantined"
                    self._notify_quarantine(
                        principal=binding.principal_id,
                        name=safe_name,
                        size=size,
                        sha256=digest.hexdigest(),
                        request_id=binding.request_id,
                    )
            receipt_name = getattr(receipt, "name", safe_name)
            return IngestReceipt(
                name=str(receipt_name),
                size=size,
                status=status,
                request_id=binding.request_id,
                sha256=getattr(receipt, "sha256", digest.hexdigest()),
            )
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


    def _notify_quarantine(
        self,
        *,
        principal: str,
        name: str,
        size: int,
        sha256: str,
        request_id: str,
    ) -> None:
        """Emit a redacted quarantine event when a notifier is configured.

        Only hashes and bounded fields leave the pipeline (threat T14). A
        notifier failure must never fail the ingest itself.
        """
        if self.notifier is None:
            return
        from .identity import hash_principal

        event = {
            "request_id": request_id,
            "principal_hash": hash_principal(principal),
            "name_hash": hashlib.sha256(name.encode("utf-8")).hexdigest(),
            "size": size,
            "sha256": sha256,
        }
        try:
            self.notifier.notify_quarantine(event=event)
        except Exception:  # noqa: BLE001 - notification must not break ingest
            return


def bounded_copy(*, src, max_bytes: int, chunk_bytes: int = 64 * 1024):
    """Yield bounded chunks from a bytes-like object or binary stream."""

    if max_bytes <= 0 or chunk_bytes <= 0:
        raise ValueError("copy limits must be positive")
    total = 0
    if isinstance(src, (bytes, bytearray)):
        source = memoryview(src)
        offset = 0
        while offset < len(source):
            chunk = bytes(source[offset : offset + chunk_bytes])
            offset += len(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise TooLarge("stream exceeds the bounded cap")
            yield chunk
        return
    while True:
        chunk = src.read(chunk_bytes)
        if not chunk:
            return
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("source must yield bytes")
        total += len(chunk)
        if total > max_bytes:
            raise TooLarge("stream exceeds the bounded cap")
        yield bytes(chunk)


__all__ = [
    "DownloadsPort",
    "IngestPipeline",
    "IngestReceipt",
    "IngestReceiptError",
    "QuarantineNotifier",
    "Scanner",
    "TooLarge",
    "bounded_copy",
]
