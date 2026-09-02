"""TDD contracts for durable owner storage and filesystem safety."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

from cloudbrowser.downloads.store import (
    DownloadNameError,
    DownloadStore,
    owner_key,
    safe_name,
)


def test_owner_key_does_not_put_principal_pii_in_the_storage_path(tmp_path: Path) -> None:
    principal = "person@example.test"
    key = owner_key(principal)
    assert key == sha256(principal.encode("utf-8")).hexdigest()
    assert "@" not in key
    assert (tmp_path / key).name == key


def test_ingest_is_atomic_and_survives_a_new_store_instance(tmp_path: Path) -> None:
    first = DownloadStore(tmp_path)
    receipt = first.ingest("person@example.test", "report.pdf", BytesIO(b"payload"))
    assert receipt.name == "report.pdf"
    assert receipt.size == 7
    assert len(receipt.sha256) == 64

    second = DownloadStore(tmp_path)
    assert second.read("person@example.test", "report.pdf") == b"payload"
    assert [entry.name for entry in second.list_entries("person@example.test")] == ["report.pdf"]


def test_ingest_rejects_oversized_payload_without_leaving_a_partial_file(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path, max_file_bytes=4)
    with pytest.raises(ValueError):
        store.ingest("person@example.test", "too-large.bin", BytesIO(b"12345"))
    assert store.read("person@example.test", "too-large.bin") is None


def test_symlinks_are_not_listed_or_read(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    entries = tmp_path / owner_key("person@example.test") / "entries"
    entries.mkdir(parents=True)
    (tmp_path / "outside.txt").write_bytes(b"outside")
    (entries / "link.txt").symlink_to(tmp_path / "outside.txt")
    assert store.list_entries("person@example.test") == []
    assert store.read("person@example.test", "link.txt") is None


def test_quarantine_is_visible_as_metadata_but_never_readable(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    quarantine = tmp_path / owner_key("person@example.test") / "quarantine"
    quarantine.mkdir(parents=True)
    (quarantine / "1700000000_bad.pdf").write_bytes(b"infected")
    entries = store.list_entries("person@example.test")
    assert len(entries) == 1
    assert entries[0].quarantined is True
    assert entries[0].qname == "1700000000_bad.pdf"
    assert store.read("person@example.test", "bad.pdf") is None


def test_safe_name_rejects_encoded_traversal_and_header_controls() -> None:
    assert safe_name("report.pdf") == "report.pdf"
    for raw in (
        "%2e%2e%2fetc%2fpasswd",
        "%252e%252e%252fetc%252fpasswd",
        "report%0d%0aX-Evil: yes",
        "report\r\nX-Evil: yes",
        "report\x01.txt",
        "a" * 256,
        ".hidden",
        "foo/bar",
        "foo\\bar",
    ):
        assert safe_name(raw) is None, raw
