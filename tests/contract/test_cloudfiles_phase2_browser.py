"""Phase 2 contract tests for the fake browser completion event seam."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from cloudbrowser.cloudfiles.browser_downloads import (
    BrowserDownloadCompleted,
    FakeBrowserDownloadSource,
    connect_browser_downloads,
)
from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.ingest import IngestPipeline


def test_completion_event_carries_binding_and_not_destination_path(tmp_path: Path) -> None:
    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "clean"

    class Downloads:
        def __init__(self):
            self.calls = []

        def publish(self, *, binding, source_name, source, size, sha256):
            self.calls.append((binding, source_name, source.read(), size, sha256))
            return SimpleNamespace(name=source_name, sha256=sha256)

        def quarantine(self, **kwargs):
            raise AssertionError

    binding = PrincipalBinding(principal_id="owner-a@example.test", request_id="event-1")
    downloads = Downloads()
    pipeline = IngestPipeline(downloads=downloads, scanner=Scanner(), temp_root=tmp_path)
    source = FakeBrowserDownloadSource()
    connect_browser_downloads(source, pipeline)
    event = BrowserDownloadCompleted(binding=binding, source_name="a.txt", source=BytesIO(b"a"))
    result = source.complete(event)

    assert result[0].request_id == "event-1"
    assert downloads.calls[0][0] == binding
    assert downloads.calls[0][2] == b"a"
    assert not hasattr(event, "principal_id")
    assert not hasattr(event, "destination")
