"""Security boundary tests for the downloads service."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.downloads.service import DownloadsService
from cloudbrowser.downloads.contracts import DownloadNameError, OwnerMismatch, PrincipalIdentity


def _identity(principal: str) -> PrincipalIdentity:
    return PrincipalIdentity(
        request_id="req-1",
        principal_id=principal,
        profile_id="profile",
        browser_id="browser-1",
        generation="generation-1",
    )


def test_listing_never_returns_other_owner_entries(tmp_path: Path) -> None:
    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "shared.pdf").write_bytes(b"%PDF-A")
    (tmp_path / "owner-b").mkdir()
    (tmp_path / "owner-b" / "private.pdf").write_bytes(b"%PDF-B")
    service = DownloadsService(store_root=tmp_path)
    listing_a = service.list_files(_identity("owner-a"))
    names = sorted(entry.name for entry in listing_a.entries)
    assert names == ["shared.pdf"]
    listing_b = service.list_files(_identity("owner-b"))
    assert [entry.name for entry in listing_b.entries] == ["private.pdf"]


def test_path_traversal_is_rejected_at_every_boundary(tmp_path: Path) -> None:
    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "ok.pdf").write_bytes(b"%PDF")
    service = DownloadsService(store_root=tmp_path)
    for raw in (
        "..",
        "../etc/passwd",
        "../../etc/passwd",
        "/etc/passwd",
        "sub/x",
    ):
        with pytest.raises(OwnerMismatch):
            service.read_file(_identity("owner-a"), raw)
    for raw in (".hidden", "a\x00b"):
        with pytest.raises(DownloadNameError):
            service.read_file(_identity("owner-a"), raw)


def test_quarantine_entries_are_never_served(tmp_path: Path) -> None:
    area = tmp_path / "owner-a"
    area.mkdir()
    quarantine = area / ".quarantine"
    quarantine.mkdir()
    (area / "good.pdf").write_bytes(b"%PDF-good")
    (quarantine / "bad.pdf").write_bytes(b"%PDF-bad")
    service = DownloadsService(store_root=tmp_path)
    listing = service.list_files(_identity("owner-a"))
    names = [entry.name for entry in listing.entries]
    assert "bad.pdf" not in names
    assert "good.pdf" in names
    assert service.read_file(_identity("owner-a"), "good.pdf") == b"%PDF-good"
