"""Phase 2 integration tests for the real downloads store adapter."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.downloads_adapter import DownloadsStoreAdapter
from cloudbrowser.cloudfiles.ingest import IngestPipeline
from cloudbrowser.downloads.service import DownloadsService
from cloudbrowser.downloads.store import owner_key


def _binding(principal: str = "owner-a@example.test") -> PrincipalBinding:
    return PrincipalBinding(principal_id=principal, request_id="request-a")


def test_real_adapter_streams_clean_payload_to_owner_store(tmp_path: Path) -> None:
    adapter = DownloadsStoreAdapter(DownloadsService(store_root=tmp_path))

    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "clean"

    result = IngestPipeline(downloads=adapter, scanner=Scanner(), temp_root=tmp_path / "staging").ingest(
        binding=_binding(), source_name="report.pdf", source=BytesIO(b"payload")
    )

    assert result.status == "published"
    assert adapter.read_file(binding=_binding(), name="report.pdf") == b"payload"
    assert adapter.read_file(binding=_binding("owner-b@example.test"), name="report.pdf") is None
    assert not list((tmp_path / "staging").iterdir())
    assert not (tmp_path / "owner-a@example.test").exists()
    assert (tmp_path / owner_key("owner-a@example.test") / "entries" / "report.pdf").is_file()


def test_real_adapter_quarantine_is_listed_as_quarantine_only(tmp_path: Path) -> None:
    adapter = DownloadsStoreAdapter(DownloadsService(store_root=tmp_path))

    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "infected"

    result = IngestPipeline(downloads=adapter, scanner=Scanner(), temp_root=tmp_path / "staging").ingest(
        binding=_binding(), source_name="bad.exe", source=BytesIO(b"bad")
    )

    assert result.status == "quarantined"
    entries = adapter.list_files(binding=_binding())["entries"]
    assert entries and entries[0]["quarantined"] is True
    assert adapter.read_file(binding=_binding(), name="bad.exe") is None
    quarantine = tmp_path / owner_key("owner-a@example.test") / "quarantine" / "bad.exe"
    assert quarantine.read_bytes() == b"bad"
