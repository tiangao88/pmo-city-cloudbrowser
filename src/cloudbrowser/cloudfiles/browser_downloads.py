"""Phase 2 browser completion seam and the production download watcher.

The browser-side half of the secure local-filesystem handoff: Chromium writes
into a server-configured download directory and ``BrowserDownloadWatcher``
emits only completed, regular, confined files under the server binding. The
fake event source remains for deterministic local integration tests.
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Callable

from .contracts import PrincipalBinding
from .filenames import validate_name
from .ingest import IngestPipeline, IngestReceipt
from cloudbrowser.owner_storage import owner_directory, prepare_owner_directory

_logger = logging.getLogger("cloudbrowser.cloudfiles.browser_downloads")


@dataclass(frozen=True)
class BrowserDownloadCompleted:
    """Completion event with a server-derived owner binding."""

    binding: PrincipalBinding
    source_name: str
    source: BinaryIO
    size: int | None = None


class FakeBrowserDownloadSource:
    """Deterministic event source for local integration tests."""

    def __init__(self) -> None:
        self._handlers: list[Callable[[BrowserDownloadCompleted], IngestReceipt]] = []

    def subscribe(self, handler: Callable[[BrowserDownloadCompleted], IngestReceipt]) -> None:
        self._handlers.append(handler)

    def complete(self, event: BrowserDownloadCompleted) -> list[IngestReceipt]:
        return [handler(event) for handler in tuple(self._handlers)]


def connect_browser_downloads(source: FakeBrowserDownloadSource, pipeline: IngestPipeline) -> None:
    """Connect browser completion events to the owner-bound pipeline."""

    def handle(event: BrowserDownloadCompleted) -> IngestReceipt:
        return pipeline.ingest(
            binding=event.binding, source_name=event.source_name, source=event.source
        )

    source.subscribe(handle)


@dataclass(frozen=True)
class DownloadWatchConfig:
    """Server-configured Chromium download directory and owner binding.

    The directory is chosen by the operator (never by the browser or the
    page); the binding is the browser's own server-derived identity.
    """

    download_dir: Path
    binding: PrincipalBinding
    max_bytes: int = 1024 * 1024 * 1024
    owner_scoped: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.download_dir, Path) or not self.download_dir.is_absolute():
            raise ValueError("download_dir must be an absolute path")
        if not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")


def completed_downloads(download_dir: Path, *, max_bytes: int) -> list[Path]:
    """Return completed, regular, confined candidates from a download directory.

    A candidate is eligible only when it is a direct child of the configured
    directory, is a regular non-symlink file, has a safe flat name, is not a
    Chromium partial (``.crdownload``), does not exceed ``max_bytes``, and
    resolves back under the configured directory.
    """

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    root = Path(download_dir).resolve(strict=False)
    try:
        children = sorted(Path(download_dir).iterdir())
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []
    candidates: list[Path] = []
    for child in children:
        if child.name.lower().endswith(".crdownload"):
            continue
        try:
            metadata = child.lstat()
        except OSError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            continue
        if validate_name(child.name) is None:
            continue
        if int(metadata.st_size) > max_bytes:
            continue
        try:
            resolved = child.resolve(strict=False)
        except OSError:
            continue
        if not resolved.is_relative_to(root):
            continue
        candidates.append(child)
    return candidates


class BrowserDownloadWatcher:
    """Emit only completed files from a server-configured download directory.

    Each completed candidate is submitted once under a fresh ``request_id``
    with the server binding. A successful submit consumes the source file; a
    failed submit keeps it for the next scan, so no download is ever lost and
    downstream duplicate handling is the safe suffixed-name semantics of the
    durable store.
    """

    def __init__(
        self,
        config: DownloadWatchConfig,
        *,
        submit: Callable[[BrowserDownloadCompleted], IngestReceipt],
    ) -> None:
        if not callable(submit):
            raise TypeError("submit must be callable")
        self._config = config
        self._root = config.download_dir
        self._lock = threading.RLock()
        if config.owner_scoped:
            self._config = replace(config, download_dir=owner_directory(self._root, config.binding.principal_id, config.binding.profile_id))
        self._submit = submit
        self._closed = False

    def update_binding(self, binding: PrincipalBinding) -> None:
        """Rotate the attribution binding after a browser rebind.

        Production rotates the owner-specific directory and attribution
        atomically with respect to scans. Pending files stay with their owner.
        """

        if not isinstance(binding, PrincipalBinding):
            raise ValueError("binding must be a PrincipalBinding")
        with self._lock:
            directory = owner_directory(self._root, binding.principal_id, binding.profile_id) if self._config.owner_scoped else self._config.download_dir
            self._config = replace(self._config, binding=binding, download_dir=directory)

    def emit_once(self) -> list[IngestReceipt]:
        with self._lock:
            return self._emit_once()

    def _emit_once(self) -> list[IngestReceipt]:
        """Scan once; emit and consume every completed candidate.

        Each candidate is handled independently: a vanished or replaced
        file (TOCTOU with a concurrent cleaner) is skipped without
        stalling the rest of the batch, and a failed submit keeps its
        file in place for the next scan (at-least-once semantics).
        """

        if self._closed:
            raise RuntimeError("watcher is closed")
        if self._config.owner_scoped:
            prepare_owner_directory(self._root, self._config.download_dir)
        else:
            self._config.download_dir.mkdir(parents=True, exist_ok=True)
        receipts: list[IngestReceipt] = []
        for path in completed_downloads(
            self._config.download_dir, max_bytes=self._config.max_bytes
        ):
            try:
                binding = replace(self._config.binding, request_id="req-" + secrets.token_hex(8))
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except FileNotFoundError:
                # A concurrent writer or cleaner removed the candidate
                # between listing and open: skip it for this scan.
                continue
            except OSError as exc:
                _logger.warning("download scan skipped unreadable file: %s", exc)
                continue
            submitted = False
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode) or int(metadata.st_size) > self._config.max_bytes:
                    continue
                with os.fdopen(descriptor, "rb") as stream:
                    descriptor = -1
                    event = BrowserDownloadCompleted(
                        binding=binding,
                        source_name=path.name,
                        source=stream,
                        size=int(metadata.st_size),
                    )
                    receipts.append(self._submit(event))
                    submitted = True
            except Exception as exc:  # noqa: BLE001 - bounded per-file boundary
                _logger.warning(
                    "download submit failed for %r (kept for retry): %s",
                    path.name,
                    exc,
                )
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if submitted:
                try:
                    path.unlink()
                except OSError:
                    # A concurrent writer replaced the file: leave it for the
                    # next scan; downstream duplicate handling is safe by
                    # construction.
                    pass
        return receipts

    def run(self, stop_event, *, interval_s: float = 1.0) -> None:
        """Poll the configured directory until ``stop_event`` is set.

        Scan failures are logged and retried with bounded exponential
        backoff so a permanent outage (receiver down, bad secret) is
        visible to the operator instead of spinning silently.
        """

        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        wait = getattr(stop_event, "wait", None)
        if not callable(wait):
            raise TypeError("stop_event must provide wait(seconds)")
        backoff_s = interval_s
        while not wait(interval_s):
            try:
                self.emit_once()
                backoff_s = interval_s
            except Exception as exc:  # noqa: BLE001 - a scan failure must not stop the watcher
                _logger.error(
                    "download watcher scan failed for %s (retrying in %.1fs): %s",
                    self._config.download_dir.name,
                    backoff_s,
                    exc,
                )
                wait(backoff_s)
                backoff_s = min(backoff_s * 2, 30.0)

    def close(self) -> None:
        """Stop accepting new emissions. Idempotent."""

        with self._lock:
            self._closed = True


__all__ = [
    "BrowserDownloadCompleted",
    "BrowserDownloadWatcher",
    "DownloadWatchConfig",
    "FakeBrowserDownloadSource",
    "completed_downloads",
    "connect_browser_downloads",
]
