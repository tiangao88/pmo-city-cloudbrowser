"""Authenticated, integrity-checked backup and restore for the downloads volume."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import posixpath
import tarfile
from typing import Any

_MANIFEST = "cloudfiles-backup-manifest.json"


def _validate_instance(instance_id: str) -> str:
    if not isinstance(instance_id, str) or not instance_id or "/" in instance_id or "\\" in instance_id:
        raise ValueError("instance_id is invalid")
    return instance_id


def _validate_destination(dest_dir: Path) -> Path:
    dest = Path(dest_dir)
    if ".." in dest.parts:
        raise ValueError("destination must not contain parent traversal")
    return dest


def _regular_files(source: Path) -> list[Path]:
    """Return regular, confined files to archive, including the index."""
    if not source.exists():
        return []
    root = source.resolve()
    result: list[Path] = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("backup source contains a symlink")
        if path.is_file():
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("backup source escapes root")
            result.append(path)
    return result


def _digest(files: list[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def backup_store(source_dir: Path, backup_tar: Path, *, instance_id: str) -> dict[str, Any]:
    """Create a deterministic tar backup and return its integrity manifest."""
    instance_id = _validate_instance(instance_id)
    source = Path(source_dir)
    files = _regular_files(source)
    manifest = {
        "instance_id": instance_id,
        "file_count": len(files),
        "sha256": _digest(files, source),
    }
    backup = Path(backup_tar)
    backup.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(backup, "w") as archive:
        info = tarfile.TarInfo(_MANIFEST)
        raw_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        info.size = len(raw_manifest)
        info.mode = 0o600
        archive.addfile(info, __import__("io").BytesIO(raw_manifest))
        for path in files:
            relative = path.relative_to(source).as_posix()
            archive.add(path, arcname=relative, recursive=False, filter=lambda member: _regular_member(member))
    return manifest


def _regular_member(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if not member.isfile() or member.name == _MANIFEST:
        return None
    return member


def restore_store(backup_tar: Path, dest_dir: Path, *, instance_id: str) -> dict[str, Any]:
    """Verify and safely extract a backup into a destination directory."""
    instance_id = _validate_instance(instance_id)
    destination = _validate_destination(Path(dest_dir))
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(backup_tar, "r") as archive:
        members = archive.getmembers()
        manifests = [member for member in members if member.name == _MANIFEST]
        if len(manifests) != 1:
            raise ValueError("backup manifest is required")
        manifest_file = archive.extractfile(manifests[0])
        if manifest_file is None:
            raise ValueError("backup manifest is unreadable")
        try:
            manifest = json.loads(manifest_file.read())
        except (ValueError, TypeError) as exc:
            raise ValueError("backup manifest is invalid") from exc
        if manifest.get("instance_id") != instance_id:
            raise ValueError("backup instance does not match destination instance")
        files = []
        root = destination.resolve()
        for member in members:
            if member.name == _MANIFEST:
                continue
            normalized = posixpath.normpath(member.name)
            target = (destination / normalized).resolve()
            if normalized in {"", "."} or normalized.startswith("../") or normalized == ".." or not target.is_relative_to(root):
                raise ValueError("backup contains a path escape")
            if not member.isfile():
                raise ValueError("backup contains a non-regular member")
            files.append(member)
        for member in files:
            archive.extract(member, destination, set_attrs=False, filter="data")
        extracted = [destination / member.name for member in files]
        actual = {
            "instance_id": instance_id,
            "file_count": len(extracted),
            "sha256": _digest(extracted, destination),
        }
        expected = {
            "instance_id": manifest.get("instance_id"),
            "file_count": manifest.get("file_count"),
            "sha256": manifest.get("sha256"),
        }
        if actual != expected:
            raise ValueError("backup integrity check failed")
    return actual


__all__ = ["backup_store", "restore_store"]
