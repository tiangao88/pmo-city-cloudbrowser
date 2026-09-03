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

    Existing ``root/<principal>`` directories remain readable for one
    compatibility release; new writes always use the hashed layout.
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
        if not isinstance(principal_id, str) or not _OWNER_PATTERN.fullmatch(principal_id):
            raise ValueError("principal_id must be bounded non-empty text")
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

    def _storage_dirs(self, principal_id: str) -> tuple[Path, ...]:
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
        return tuple(dirs)

    def list_entries(self, principal_id: str) -> list[DownloadEntry]:
        """Return bounded metadata for canonical and prior files."""

        dirs = self._storage_dirs(principal_id)
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
                qname = safe_name(child.name)
                if not stat_module.S_ISREG(metadata.st_mode) or stat_module.S_ISLNK(metadata.st_mode) or qname is None:
                    continue
                result.append(
                    DownloadEntry(
                        name=qname,
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
        for path in (self._owner_root(principal_id) / _INDEX_FILE, self._prior_owner_root(principal_id) / _INDEX_FILE):
            try:
                data = json.loads(path.read_text())
                value = data.get(name, {}).get("sha256")
                if isinstance(value, str) and len(value) == 64:
                    return value
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return None

    def read(self, principal_id: str, name: str) -> bytes | None:
        """Read a regular, non-symlink entry; quarantine is never readable."""

        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        for entries_dir in self._storage_dirs(principal_id):
            path = entries_dir / safe
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
            try:
                metadata = os.fstat(descriptor)
                if not stat_module.S_ISREG(metadata.st_mode) or metadata.st_size > self.max_file_bytes:
                    continue
                with os.fdopen(descriptor, "rb") as handle:
                    descriptor = -1
                    payload = handle.read(self.max_file_bytes + 1)
                return None if len(payload) > self.max_file_bytes else payload
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
        final_name = self._next_name(entries_dir, safe)
        temp = entries_dir / f".{final_name}.{secrets.token_hex(8)}.tmp"
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
            final = entries_dir / final_name
            os.replace(temp, final)
            stat_result = final.lstat()
            receipt = DownloadReceipt(
                name=final.name,
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

    @staticmethod
    def _next_name(entries_dir: Path, safe: str) -> str:
        """Choose a flat ``name (n).ext`` suffix without overwriting."""

        if not (entries_dir / safe).exists():
            return safe
        stem, dot, extension = safe.rpartition(".")
        if not dot:
            stem, extension = safe, ""
        suffix = f".{extension}" if extension else ""
        for index in range(1, 1001):
            candidate = f"{stem} ({index}){suffix}"
            if not (entries_dir / candidate).exists():
                return candidate
        raise ValueError("download name space exhausted")

    def quarantine(self, principal_id: str, name: str, source: BinaryIO) -> DownloadReceipt:
        """Store a staged non-clean stream under the quarantine directory."""

        safe = safe_name(name)
        if safe is None:
            raise DownloadNameError("download name is unsafe")
        if not hasattr(source, "read"):
            raise ValueError("source must be a binary stream")
        self.root.mkdir(parents=True, exist_ok=True)
        owner_root = self._owner_root(principal_id)
        quarantine_dir = self._quarantine_dir(principal_id)
        self._assert_under_root(quarantine_dir)
        self._assert_directory(owner_root)
        owner_root.mkdir(exist_ok=True)
        self._assert_directory(quarantine_dir)
        quarantine_dir.mkdir(exist_ok=True)
        for index in range(1001):
            candidate = quarantine_dir / (safe if index == 0 else f"{safe} ({index})")
            try:
                descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                continue
        else:
            raise ValueError("quarantine name space exhausted")
        digest = sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb", buffering=0) as target:
                descriptor = -1
                while True:
                    chunk = source.read(64 * 1024)
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
            metadata = candidate.lstat()
            return DownloadReceipt(
                name=candidate.name,
                size=size,
                mtime=int(metadata.st_mtime),
                sha256=digest.hexdigest(),
                owner=principal_id,
            )
        except Exception:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)

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
        data[receipt.name] = {"size": receipt.size, "mtime": receipt.mtime, "sha256": receipt.sha256}
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


__all__ = ["DownloadStore", "DownloadEntry", "DownloadNameError", "DownloadReceipt", "owner_key", "safe_name"]
