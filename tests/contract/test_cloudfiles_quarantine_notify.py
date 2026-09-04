"""Phase 4 quarantine notification seam (threat T14 redaction)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.downloads_adapter import DownloadsStoreAdapter
from cloudbrowser.cloudfiles.ingest import IngestPipeline
from cloudbrowser.downloads.service import DownloadsService


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def notify_quarantine(self, *, event: dict[str, object]) -> None:
        self.events.append(dict(event))


def _binding() -> PrincipalBinding:
    return PrincipalBinding(
        principal_id="owner-a@example.test",
        request_id="request-q",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-1",
    )


class _InfectedScanner:
    def scan(self, path: Path, *, request_id: str) -> str:
        return "infected"


def test_quarantine_publish_emits_bounded_notification(tmp_path: Path) -> None:
    notifier = RecordingNotifier()
    adapter = DownloadsStoreAdapter(DownloadsService(store_root=tmp_path))
    pipeline = IngestPipeline(
        downloads=adapter,
        scanner=_InfectedScanner(),
        temp_root=tmp_path / "staging",
        notifier=notifier,
    )
    result = pipeline.ingest(
        binding=_binding(),
        source_name="bad.exe",
        source=BytesIO(b"infected-payload"),
    )
    assert result.status == "quarantined"
    assert len(notifier.events) == 1
    event = notifier.events[0]
    assert event["request_id"] == "request-q"
    assert event["principal_hash"]
    assert event["name_hash"]
    assert event["size"] == len(b"infected-payload")
    # Threat T14: the raw principal and filename must never appear.
    blob = str(event)
    assert "owner-a@example.test" not in blob
    assert "bad.exe" not in blob


def test_clean_ingest_emits_no_notification(tmp_path: Path) -> None:
    notifier = RecordingNotifier()
    adapter = DownloadsStoreAdapter(DownloadsService(store_root=tmp_path))

    class Clean:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "clean"

    pipeline = IngestPipeline(
        downloads=adapter,
        scanner=Clean(),
        temp_root=tmp_path / "staging",
        notifier=notifier,
    )
    pipeline.ingest(
        binding=_binding(),
        source_name="ok.pdf",
        source=BytesIO(b"clean"),
    )
    assert notifier.events == []
