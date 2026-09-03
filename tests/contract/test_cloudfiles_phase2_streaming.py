"""Phase 2 integration tests for streaming staged content to downloads."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.ingest import IngestPipeline


def _binding() -> PrincipalBinding:
    return PrincipalBinding(principal_id="owner-a@example.test", request_id="request-a")


def test_pipeline_passes_rewindable_stream_and_metadata_to_clean_port(tmp_path: Path) -> None:
    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            assert path.exists()
            return "clean"

    class Downloads:
        def __init__(self):
            self.calls = []
        def publish(self, **kwargs):
            self.calls.append(kwargs)
            assert kwargs["source"].read() == b"payload"
            assert kwargs["size"] == 7
            assert len(kwargs["sha256"]) == 64
            return SimpleNamespace(name="report.pdf", sha256=kwargs["sha256"])
        def quarantine(self, **kwargs):
            raise AssertionError

    downloads = Downloads()
    receipt = IngestPipeline(downloads=downloads, scanner=Scanner(), temp_root=tmp_path).ingest(
        binding=_binding(), source_name="report.pdf", source=BytesIO(b"payload")
    )
    assert receipt.status == "published"
    assert not list(tmp_path.iterdir())


def test_pipeline_passes_staged_stream_to_quarantine_port(tmp_path: Path) -> None:
    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "infected"
    class Downloads:
        def publish(self, **kwargs):
            raise AssertionError
        def quarantine(self, **kwargs):
            assert kwargs["source"].read() == b"bad"
            assert kwargs["size"] == 3
            return SimpleNamespace(name="bad.exe", sha256=kwargs["sha256"])

    result = IngestPipeline(downloads=Downloads(), scanner=Scanner(), temp_root=tmp_path).ingest(
        binding=_binding(), source_name="bad.exe", source=BytesIO(b"bad")
    )
    assert result.status == "quarantined"
