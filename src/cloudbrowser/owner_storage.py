"""Stable installation-local owner paths, independent of slot and generation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def owner_directory(root: Path, principal_id: str, profile_id: str) -> Path:
    for value in (principal_id, profile_id):
        if not isinstance(value, str) or not value or len(value.encode()) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("owner identity is invalid")
    if not root.is_absolute():
        raise ValueError("owner root must be absolute")
    key = hashlib.sha256(json.dumps([principal_id, profile_id], separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    return root / "owners-v1" / key


def prepare_owner_directory(root: Path, directory: Path) -> None:
    """Only create known layout components; never follow an owner symlink."""
    relative = directory.relative_to(root)
    if len(relative.parts) != 2 or relative.parts[0] != "owners-v1":
        raise ValueError("invalid owner directory")
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        if current.is_symlink():
            raise ValueError("owner directory is a symlink")
        current.mkdir(mode=0o700, parents=part is None, exist_ok=True)
        if not current.is_dir():
            raise ValueError("owner directory is unavailable")
