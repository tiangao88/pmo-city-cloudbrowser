"""Durable, per-principal filesystem store for download objects."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import stat as stat_module
from typing import BinaryIO
from urllib.parse import unquote

from .contracts import DownloadEntry, DownloadNameError, DownloadReceipt


_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]{0,255}$")
_NAME_MAX = 255
_MAX_DEFAULT = 5 * 1024 * 1024 * 1024
_QUARANTINE_DIR = "quarantine"
_ENTRIES_DIR = "entries"
_INDEX_FILE = ".index.json"


def owner_key(principal_id: str) -> str:
    """Derive a stable non-PII directory key from a principal identifier."""

    if not isinstance(principal_id, str) or not _OWNER_PATTERN.fullmatch(principal_id):
        raise ValueError("principal_id must be bounded non-empty text")
    return sha256(principal_id.encode("utf-8")).hexdigest()


def safe_name(raw: object) -> str | None:
    """Decode once and accept only a flat, printable, non-hidden filename."""

    if not isinstance(raw, str) or not raw or len(raw) > _NAME_MAX * 3:
        return None
    try:
        name = unquote(raw, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if "%" in name or not name or len(name) > _NAME_MAX:
        return None
    if name in {".", ".."} or name.startswith("."):
        return None
    if "/" in name or "\\" in name or "\x00" in name:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in name):
        return None
    return name


@dataclass(frozen=True)
class DownloadStore:
    """Persist owner files under ``root/<sha256(principal)>/entries``.

    The hashed layout is the canonical layout. For one compatibility release,
    reads also accept the prior plain owner directory when it is already
    present; all new ingests use the hashed layout and never create a PII
    path.
    """

    root: Path
    max_file_bytes: int = _MAX_DEFAULT
    max_entries: int = 1000

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        if not isinstance(self.max_file_bytes, int) or self.max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if not isinstance(self.max_entries, int) or self.max_entries <= 0:
            raise ValueError("max_entries must be positive")

    def _owner_root(self, principal_id: str) -> Path:
        return self.root / owner_key(principal_id)

    def _prior_owner_root(self, principal_id: str) -> Path:
        if not isinstance(principal_id, str) or not _OWNER_PATTERN.fullmatch(principal_id):
            raise ValueError("principal_id must be bounded non-empty text")
        return self.root / principal_id

    def _entries_dir(self, principal_id: str) -> Path:
        return self._owner_root(principal_id) / _ENTRIES_DIR

    def _prior_entries_dir(self, principal_id: str) -> Path:
        return self._prior_owner_root(principal_id)

    def _quarantine_dir(self, principal_id: str) -> Path:
        return self._owner_root(principal_id) / _QUARANTINE_DIR

    def _prior_quarantine_dir(self, principal_id: str) -> Path:
        return self._prior_owner_root(principal_id) / ".quarantine"

    def _assert_directory(self, path: Path) -> None:
        """Reject symlinked storage directories before traversing them."""

        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return
        if stat_module.S_ISLNK(metadata.st_mode) or not stat_module.S_ISDIR(metadata.st_mode):
            raise ValueError("download storage directory is unsafe")

    def _assert_under_root(self, path: Path) -> None:
        root = self.root.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise ValueError("download storage escapes configured root")

    def _prepare_entries_dir(self, principal_id: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        owner_root = self._owner_root(principal_id)
        self._assert_under_root(owner_root)
        self._assert_directory(owner_root)
        owner_root.mkdir(exist_ok=True)
        entries_dir = owner_root / _ENTRIES_DIR
        self._assert_directory(entries_dir)
        entries_dir.mkdir(exist_ok=True)
        return entries_dir

    def list_entries(self, principal_id: str) -> list[DownloadEntry]:
        """Return bounded metadata from canonical and prior entries."""

        canonical = self._entries_dir(principal_id)
        prior = self._prior_entries_dir(principal_id)
        self._assert_under_root(canonical)
        self._assert_directory(self._owner_root(principal_id))
        self._assert_directory(canonical)
        self._assert_directory(prior)
        dirs: list[Path] = []
        for path in (canonical, prior):
            try:
                if path.is_dir() and not path.is_symlink():
                    dirs.append(path)
            except OSError:
                continue
        result: list[DownloadEntry] = []
        seen: set[str] = set()
        for entries_dir in dirs:
            try:
                children = sorted(entries_dir.iterdir())
            except (FileNotFoundError, NotADirectoryError):
                continue
            for child in children:
                if len(result) >= self.max_entries:
                    break
                if child.name in seen or safe_name(child.name) is None:
                    continue
                try:
                    metadata = child.lstat()
                except FileNotFoundError:
                    continue
                if not stat_module.S_ISREG(metadata.st_mode) or stat_module.S_ISLNK(metadata.st_mode):
                    continue
                seen.add(child.name)
                result.append(
                    DownloadEntry(
                        name=child.name,
                        size=int(metadata.st_size),
                        mtime=int(metadata.st_mtime),
                        owner=principal_id,
                        sha256=self._read_index_hash(principal_id, child.name),
                    )
                )
        quarantine_dirs = (self._quarantine_dir(principal_id), self._prior_quarantine_dir(principal_id))
        for quarantine in quarantine_dirs:
            try:
                self._assert_directory(quarantine)
                quarantine_entries = sorted(quarantine.iterdir())
            except (FileNotFoundError, NotADirectoryError):
                continue
            for child in quarantine_entries:
                if len(result) >= self.max_entries:
                    break
                try:
                    metadata = child.lstat()
                except FileNotFoundError:
                    continue
                if not stat_module.S_ISREG(metadata.st_mode) or stat_module.S_ISLNK(metadata.st_mode):
                    continue
                qname = safe_name(child.name)
                if qname is None:
                    continue
                original = qname.split("_", 1)[1] if "_" in qname else qname
                if safe_name(original) is None:
                    continue
                result.append(
                    DownloadEntry(
                        name=original,
                        size=int(metadata.st_size),
                        mtime=int(metadata.st_mtime),
                        owner=principal_id,
                        quarantined=True,
                        qname=qname,
                    )
                )
        result.sort(key=lambda entry: entry.mtime, reverse=True)
        return result

    def _read_index_hash(self, principal_id: str, name: str) -> str | None:
        try:
            data = json.loads((self._owner_root(principal_id) / _INDEX_FILE).read_text())
            value = data.get(name, {}).get("sha256")
            return value if isinstance(value, str) and len(value) == 64 else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def read(self, principal_id: str, name: str) -> bytes | None:
        """Read a regular, non-symlink entry; quarantine is never readable."""

        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        canonical = self._entries_dir(principal_id)
        prior = self._prior_entries_dir(principal_id)
        self._assert_under_root(canonical)
        self._assert_directory(self._owner_root(principal_id))
        self._assert_directory(canonical)
        self._assert_directory(prior)
        candidates = [canonical / safe]
        if prior != self._owner_root(principal_id):
            candidates.append(prior / safe)
        for path in candidates:
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError:
                continue
            try:
                metadata = os.fstat(descriptor)
                if not stat_module.S_ISREG(metadata.st_mode) or metadata.st_size > self.max_file_bytes:
                    continue
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    payload = handle.read(self.max_file_bytes + 1)
                if len(payload) > self.max_file_bytes:
                    return None
                return payload
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        return None

    def ingest(self, principal_id: str, name: str, source: BinaryIO) -> DownloadReceipt:
        """Atomically store a bounded binary stream and update its index."""

        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        if not hasattr(source, "read"):
            raise ValueError("source must be a binary stream")
        entries_dir = self._prepare_entries_dir(principal_id)
        owner_root = self._owner_root(principal_id)
        temp = entries_dir / f".{safe}.{secrets.token_hex(8)}.tmp"
        digest = sha256()
        size = 0
        try:
            with temp.open("xb") as target:
                while True:
                    chunk = source.read(min(1024 * 1024, self.max_file_bytes + 1))
                    if not isinstance(chunk, (bytes, bytearray)):
                        raise ValueError("source must yield bytes")
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_file_bytes:
                        raise ValueError("download exceeds size limit")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            final = entries_dir / safe
            os.replace(temp, final)
            stat_result = final.lstat()
            receipt = DownloadReceipt(
                name=safe,
                size=size,
                mtime=int(stat_result.st_mtime),
                sha256=digest.hexdigest(),
                owner=principal_id,
            )
            self._write_index(principal_id, receipt)
            return receipt
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    def _write_index(self, principal_id: str, receipt: DownloadReceipt) -> None:
        owner_root = self._owner_root(principal_id)
        owner_root.mkdir(parents=True, exist_ok=True)
        index = owner_root / _INDEX_FILE
        try:
            data = json.loads(index.read_text())
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        data[receipt.name] = {
            "size": receipt.size,
            "mtime": receipt.mtime,
            "sha256": receipt.sha256,
        }
        temp = owner_root / f".{_INDEX_FILE}.{secrets.token_hex(8)}.tmp"
        try:
            with temp.open("x", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, index)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "DownloadStore",
    "DownloadEntry",
    "DownloadNameError",
    "DownloadReceipt",
    "owner_key",
    "safe_name",
]
