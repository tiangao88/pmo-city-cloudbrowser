"""Durable per-owner disk store for downloads."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .contracts import DownloadEntry, DownloadNameError


_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,256}$")
_NAME_PATTERN = re.compile(r"^[^/\\\x00]{1,256}$")
_QUARANTINE_DIR = ".quarantine"


@dataclass(frozen=True)
class DownloadStore:
    """Resolve and serve one bounded per-owner download area."""

    root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            self.root = Path(self.root)
        # The root directory is created lazily on the first operation so the
        # service can be constructed on read-only volumes or before mount.

    def _area(self, owner: str) -> Path:
        if not isinstance(owner, str) or not _OWNER_PATTERN.fullmatch(owner):
            raise ValueError("owner must be DNS-safe non-empty text")
        return self.root / owner

    def list_entries(self, owner: str) -> list[DownloadEntry]:
        """Return bounded metadata for files in the owner's durable area."""

        area = self._area(owner)
        if not area.exists():
            return []
        entries: list[DownloadEntry] = []
        for child in sorted(area.iterdir()):
            if not child.is_file():
                continue
            if child.name == _QUARANTINE_DIR:
                continue
            if child.name.startswith("."):
                continue
            if safe_name(child.name) is None:
                continue
            stat = child.stat()
            entries.append(
                DownloadEntry(
                    name=child.name,
                    size=int(stat.st_size),
                    mtime=int(stat.st_mtime),
                    owner=owner,
                )
            )
        entries.sort(key=lambda entry: entry.mtime, reverse=True)
        return entries

    def read(self, owner: str, name: str) -> bytes | None:
        """Return the bounded file bytes for an owner, or None when absent."""

        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        area = self._area(owner)
        path = area / safe
        if not path.is_file():
            return None
        # Defensive: ensure resolved path stays inside the owner area.
        try:
            resolved = path.resolve(strict=True)
            area_resolved = area.resolve(strict=False)
        except FileNotFoundError:
            return None
        if not resolved.is_relative_to(area_resolved):
            raise DownloadNameError("download name escapes owner area")
        return path.read_bytes()


def safe_name(raw: object) -> str | None:
    """Return a safe basename for download operations, or None when rejected."""

    if not isinstance(raw, str) or not raw:
        return None
    if "/" in raw or "\\" in raw or "\x00" in raw:
        return None
    name = raw
    if not name or name == "." or name == "..":
        return None
    if name.startswith("."):
        return None
    if not _NAME_PATTERN.fullmatch(name):
        return None
    return name


__all__ = ["DownloadStore", "safe_name", "DownloadEntry", "DownloadNameError"]
