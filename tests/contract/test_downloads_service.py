"""Contract tests for the bounded downloads service surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.downloads.contracts import (
    DownloadNameError,
    DownloadRequest,
    DownloadResponse,
    OwnerMismatch,
    PrincipalIdentity,
)
from cloudbrowser.downloads.service import DownloadsService


def _identity(principal: str = "owner-a") -> PrincipalIdentity:
    return PrincipalIdentity(
        request_id="req-1",
        principal_id=principal,
        profile_id="profile-a",
        browser_id="browser-1",
        generation="generation-1",
    )


def test_service_lists_files_for_owner(tmp_path: Path) -> None:
    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "invoice.pdf").write_bytes(b"%PDF-1")
    service = DownloadsService(store_root=tmp_path)
    response = service.list_files(_identity())
    assert response.principal_id == "owner-a"
    names = sorted(entry.name for entry in response.entries)
    assert names == ["invoice.pdf"]


def test_service_rejects_cross_owner_reads(tmp_path: Path) -> None:
    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "invoice.pdf").write_bytes(b"%PDF-1")
    (tmp_path / "owner-b").mkdir()
    (tmp_path / "owner-b" / "secret.pdf").write_bytes(b"%PDF-2")
    service = DownloadsService(store_root=tmp_path)
    payload = service.read_file(_identity("owner-a"), "invoice.pdf")
    assert payload == b"%PDF-1"
    with pytest.raises(OwnerMismatch):
        service.read_file(_identity("owner-a"), "../owner-b/secret.pdf")
    with pytest.raises(OwnerMismatch):
        service.read_file(_identity("owner-a"), "a/b")


def test_service_bounded_request_validation(tmp_path: Path) -> None:
    service = DownloadsService(store_root=tmp_path)
    for raw in ("", "x" * 1025, None):  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            DownloadRequest(name=raw, request_id="req-1")  # type: ignore[arg-type]


def test_service_response_never_carries_blob_bytes(tmp_path: Path) -> None:
    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "a.pdf").write_bytes(b"%PDF")
    service = DownloadsService(store_root=tmp_path)
    listing: DownloadResponse = service.list_files(_identity())
    payload = service.read_file(_identity(), "a.pdf")
    assert payload == b"%PDF"
    # The listing envelope never holds file bytes; only metadata.
    assert not any(hasattr(entry, "content") for entry in listing.entries)
    # The blob response is bytes only — never persisted via response metadata.
    assert isinstance(payload, (bytes, bytearray))


def test_service_refuses_unsafe_names(tmp_path: Path) -> None:
    service = DownloadsService(store_root=tmp_path)
    # Names containing path separators are owner-escape attempts.
    for raw in ("a/b", "a\x00b", "..", "../etc/passwd", "/etc/passwd"):
        with pytest.raises((DownloadNameError, OwnerMismatch)):
            service.read_file(_identity(), raw)
    # Hidden files are rejected outright.
    for raw in (".hidden",):
        with pytest.raises(DownloadNameError):
            service.read_file(_identity(), raw)


def test_service_returns_not_found_for_missing_owners(tmp_path: Path) -> None:
    service = DownloadsService(store_root=tmp_path)
    assert service.read_file(_identity("never-seen"), "anything.pdf") is None


def test_service_returns_principal_id_in_listing(tmp_path: Path) -> None:
    service = DownloadsService(store_root=tmp_path)
    response = service.list_files(_identity("owner-a"))
    assert response.principal_id == "owner-a"
