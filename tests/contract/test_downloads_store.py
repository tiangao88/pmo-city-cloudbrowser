"""Contract tests for the durable per-owner downloads store."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.downloads.store import (
    DownloadEntry,
    DownloadNameError,
    DownloadStore,
    safe_name,
)


def _populate(root: Path, owner: str, names: list[str]) -> list[Path]:
    area = root / owner
    area.mkdir(parents=True)
    paths: list[Path] = []
    for name in names:
        path = area / name
        path.write_bytes(b"hello")
        paths.append(path)
    return paths


def test_safe_name_rejects_unsafe_inputs() -> None:
    assert safe_name("invoice.pdf") == "invoice.pdf"
    assert safe_name("résumé.pdf") == "résumé.pdf"
    for raw in ("", ".", "..", "..\\..", "../etc/passwd", "/etc/passwd", ".hidden", "/abs/x"):
        assert safe_name(raw) is None, raw
    for raw in ("foo/bar", "foo\\bar", "foo\x00bar"):
        assert safe_name(raw) is None, raw


def test_store_persists_entries_under_owner_root(tmp_path: Path) -> None:
    _populate(tmp_path, "owner-a", ["a.txt", "b.txt"])
    store = DownloadStore(tmp_path)
    entries = store.list_entries("owner-a")
    names = sorted(entry.name for entry in entries)
    assert names == ["a.txt", "b.txt"]
    assert all(isinstance(entry, DownloadEntry) for entry in entries)
    assert all(entry.owner == "owner-a" for entry in entries)


def test_store_segregates_entries_by_owner(tmp_path: Path) -> None:
    _populate(tmp_path, "owner-a", ["a.txt"])
    _populate(tmp_path, "owner-b", ["b.txt"])
    store = DownloadStore(tmp_path)
    assert [entry.name for entry in store.list_entries("owner-a")] == ["a.txt"]
    assert [entry.name for entry in store.list_entries("owner-b")] == ["b.txt"]
    assert store.list_entries("owner-c") == []


def test_store_rejects_owner_path_traversal(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    for owner in ("", "../etc", "owner/sub", "owner\x00bad", "../"):
        with pytest.raises(ValueError):
            store.list_entries(owner)


def test_store_serves_only_safe_relative_paths(tmp_path: Path) -> None:
    area = tmp_path / "owner-a"
    area.mkdir()
    (area / "a.txt").write_bytes(b"hello")
    sub = area / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"nested")
    store = DownloadStore(tmp_path)
    payload = store.read("owner-a", "a.txt")
    assert payload == b"hello"
    with pytest.raises(DownloadNameError):
        store.read("owner-a", "../etc/passwd")
    with pytest.raises(DownloadNameError):
        store.read("owner-a", "/etc/passwd")
    with pytest.raises(DownloadNameError):
        store.read("owner-a", ".hidden")
    with pytest.raises(DownloadNameError):
        store.read("owner-a", "sub/b.txt")


def test_store_returns_empty_for_missing_owner_area(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    assert store.list_entries("never-seen") == []
    assert store.read("never-seen", "nope.txt") is None
