"""Durable per-principal storage for CloudFiles.

Implements threat T2 (cross-principal isolation), T4 (path traversal),
T8 (quarantine retrieval), T10 (GDPR erasure), T13 (symlink and
special-file escape), and T14 (log leakage) at the storage layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import stat
from typing import Iterable

from .contracts import (
    FileEntry,
    InvalidName,
    NotFound,
    OwnerMismatch,
)
from .filenames import require_name, validate_name


_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]{0,255}$")
_ENTRIES = "entries"
_QUARANTINE = "quarantine"


@dataclass(frozen=True)
class StorePaths:
    """Filesystem layout for one principal's area."""

    owner_root: Path
    entries_dir: Path
    quarantine_dir: Path

    def assert_under_root(self, candidate: Path) -> None:
        """Raise OwnerMismatch if `candidate` is not under `owner_root`."""

        try:
            candidate = candidate.resolve(strict=False)
        except OSError:
            raise OwnerMismatch("candidate cannot be resolved") from None
        root = self.owner_root.resolve(strict=False)
        if os.path.commonpath([str(candidate), str(root)]) != str(root):
            raise OwnerMismatch("candidate escapes the owner area")


class DownloadStore:
    """Per-principal download area with bounded traversal safety."""

    def __init__(self, store_root: Path, *, max_name_length: int = 255) -> None:
        self._root = Path(store_root)
        self._max_name_length = max_name_length

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _paths(self, principal: str) -> StorePaths:
        if not _OWNER.fullmatch(principal or ""):
            raise OwnerMismatch("principal must be bounded non-PII text")
        owner_root = (self._root / principal).resolve(strict=False)
        entries = owner_root / _ENTRIES
        quarantine = owner_root / _QUARANTINE
        return StorePaths(owner_root=owner_root, entries_dir=entries,
                          quarantine_dir=quarantine)

    def resolve_safe_path(self, *, principal: str, name: str) -> Path:
        """Resolve a candidate path under the principal's entries dir.

        Raises `OwnerMismatch` for any path that escapes the owner area.
        """

        safe = require_name(name)
        paths = self._paths(principal)
        candidate = (paths.entries_dir / safe).resolve(strict=False)
        paths.assert_under_root(candidate)
        if not str(candidate).startswith(str(paths.entries_dir.resolve(strict=False)) + os.sep):
            raise OwnerMismatch("candidate escapes the entries dir")
        return candidate

    # ------------------------------------------------------------------
    # Listing and reading
    # ------------------------------------------------------------------

    def list_entries(self, *, principal: str, store_root: Path | None = None) -> list[str]:
        """Return safe flat filenames in the principal's entries dir."""

        if store_root is not None:
            root = Path(store_root)
            owner_root = (root / principal).resolve(strict=False)
            entries = owner_root / _ENTRIES
        else:
            paths = self._paths(principal)
            owner_root = paths.owner_root
            entries = paths.entries_dir
        if not owner_root.exists():
            return []
        if not entries.exists():
            return []
        names: list[str] = []
        for child in entries.iterdir():
            try:
                st = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if child.name.startswith("."):
                continue
            safe = validate_name(child.name)
            if safe is None:
                continue
            names.append(safe)
        names.sort()
        return names

    def list_metadata(self, *, principal: str) -> list[FileEntry]:
        """Return bounded metadata for the principal's entries."""

        paths = self._paths(principal)
        if not paths.owner_root.exists():
            return []
        if not paths.entries_dir.exists():
            return []
        entries: list[FileEntry] = []
        for child in paths.entries_dir.iterdir():
            try:
                st = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            safe = validate_name(child.name)
            if safe is None:
                continue
            entries.append(
                FileEntry(name=safe, size=int(st.st_size), mtime=int(st.st_mtime)),
            )
        entries.sort(key=lambda e: e.name)
        return entries

    def read(self, *, principal: str, store_root: Path | None, name: str) -> bytes | None:
        """Read a file from the principal's entries dir.

        Refuses:
        - non-regular files (symlinks, sockets, dirs)
        - names under `quarantine/`
        - paths that escape the owner area
        Returns `None` if the file does not exist.
        """

        if validate_name(name) is None:
            raise InvalidName("filename is unsafe")
        if store_root is not None:
            root = Path(store_root)
            owner_root = (root / principal).resolve(strict=False)
            entries = owner_root / _ENTRIES
            quarantine = owner_root / _QUARANTINE
        else:
            paths = self._paths(principal)
            owner_root = paths.owner_root
            entries = paths.entries_dir
            quarantine = paths.quarantine_dir
        candidate = (entries / name).resolve(strict=False)
        if str(candidate).startswith(str(quarantine.resolve(strict=False)) + os.sep):
            raise NotFound("file is quarantined")
        if not str(candidate).startswith(str(entries.resolve(strict=False)) + os.sep):
            raise OwnerMismatch("candidate escapes the entries dir")
        if not candidate.exists():
            return None
        try:
            st = candidate.stat(follow_symlinks=False)
        except OSError:
            return None
        if not stat.S_ISREG(st.st_mode):
            raise InvalidName("file is not a regular file")
        return candidate.read_bytes()

    # ------------------------------------------------------------------
    # Ingest and quarantine
    # ------------------------------------------------------------------

    def publish(self, *, principal: str, source_name: str, content: bytes) -> str:
        """Publish a clean file under the principal's entries dir.

        Returns the safe final name. Caller must have already scanned the
        payload and confirmed it is clean.
        """

        safe = require_name(source_name)
        paths = self._paths(principal)
        paths.owner_root.mkdir(parents=True, exist_ok=True)
        paths.entries_dir.mkdir(parents=True, exist_ok=True)
        existing = {entry.name for entry in self.list_metadata(principal=principal)}
        if safe in existing:
            from .filenames import allocate_duplicate
            safe = allocate_duplicate(safe, existing)
        target = (paths.entries_dir / safe).resolve(strict=False)
        paths.assert_under_root(target)
        target.write_bytes(content)
        os.chmod(target, 0o640)
        return safe

    def quarantine(self, *, principal: str, source_name: str, content: bytes) -> str:
        """Move a payload to the principal's quarantine area."""

        safe = require_name(source_name)
        paths = self._paths(principal)
        paths.owner_root.mkdir(parents=True, exist_ok=True)
        paths.quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = (paths.quarantine_dir / safe).resolve(strict=False)
        paths.assert_under_root(target)
        target.write_bytes(content)
        os.chmod(target, 0o600)
        return safe

    # ------------------------------------------------------------------
    # Erasure
    # ------------------------------------------------------------------

    def erase(self, *, principal: str) -> None:
        """Erase every reference to a principal under the store root."""

        paths = self._paths(principal)
        if paths.owner_root.exists():
            _rmtree(paths.owner_root)


# ---------------------------------------------------------------------------
# Stateless helpers for the contract tests
# ---------------------------------------------------------------------------


def _make_store(store_root: Path | None) -> DownloadStore:
    return DownloadStore(store_root or Path("/data/downloads"))


def read(principal: str, store_root: Path, name: str) -> bytes | None:
    """Stateless read helper for the boundary test suite."""

    return _make_store(store_root).read(principal=principal,
                                          store_root=store_root, name=name)


def list_entries(principal: str, store_root: Path) -> list[str]:
    """Stateless listing helper for the boundary test suite."""

    return _make_store(store_root).list_entries(principal=principal,
                                                  store_root=store_root)


def resolve_safe_path(*, principal: str, store_root: Path, name: str) -> Path:
    """Stateless safe-path resolver for the boundary test suite."""

    return _make_store(store_root).resolve_safe_path(principal=principal, name=name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rmtree(path: Path) -> None:
    """Recursively remove a directory without following symlinks."""

    for child in path.iterdir():
        try:
            st = child.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            child.unlink()
            continue
        if stat.S_ISDIR(st.st_mode):
            _rmtree(child)
        else:
            child.unlink()
    path.rmdir()


def mtime_from_datetime(value: datetime) -> int:
    """Convert a UTC datetime to a bounded integer mtime."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


__all__ = [
    "DownloadStore",
    "mtime_from_datetime",
    "read",
    "list_entries",
    "resolve_safe_path",
]
