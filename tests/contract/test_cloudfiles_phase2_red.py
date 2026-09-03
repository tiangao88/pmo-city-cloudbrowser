"""Phase 2 contract tests for bounded browser-download ingest."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding


def _binding(principal: str = "owner-a@example.test") -> PrincipalBinding:
    return PrincipalBinding(
        principal_id=principal,
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
        request_id="request-a",
    )


class _Scanner:
    def __init__(self, result: str = "clean") -> None:
        self.result = result
        self.calls: list[tuple[Path, str]] = []

    def scan(self, path: Path, *, request_id: str) -> str:
        self.calls.append((path, request_id))
        assert path.is_file()
        return self.result


class _Downloads:
    def __init__(self) -> None:
        self.publish_calls: list[dict[str, object]] = []
        self.quarantine_calls: list[dict[str, object]] = []

    def publish(self, *, binding, source_name, source, size, sha256):
        content = source.read()
        self.publish_calls.append({
            "binding": binding,
            "source_name": source_name,
            "content": content,
            "size": size,
            "sha256": sha256,
        })
        return SimpleNamespace(name=source_name, sha256=sha256)

    def quarantine(self, *, binding, source_name, source, size, sha256):
        content = source.read()
        self.quarantine_calls.append({
            "binding": binding,
            "source_name": source_name,
            "content": content,
            "size": size,
            "sha256": sha256,
        })
        return SimpleNamespace(name=source_name, sha256=sha256)


def test_clean_ingest_scans_before_streaming_to_internal_downloads(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.ingest import IngestPipeline

    scanner = _Scanner()
    downloads = _Downloads()
    pipeline = IngestPipeline(downloads=downloads, scanner=scanner, temp_root=tmp_path)
    receipt = pipeline.ingest(binding=_binding(), source_name="report.pdf", source=BytesIO(b"payload"))

    assert receipt.name == "report.pdf"
    assert receipt.status == "published"
    assert scanner.calls and scanner.calls[0][1] == "request-a"
    assert downloads.publish_calls[0]["content"] == b"payload"
    assert downloads.publish_calls[0]["size"] == 7
    assert not list(tmp_path.iterdir())


def test_ingest_stages_with_private_file_permissions(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.ingest import IngestPipeline
    import os
    import stat

    scanner = _Scanner()
    downloads = _Downloads()
    observed: dict[str, int] = {}

    def publish(*, binding, source_name, source, size, sha256):
        observed["mode"] = stat.S_IMODE(os.fstat(source.fileno()).st_mode)
        return SimpleNamespace(name=source_name, sha256=sha256)

    downloads.publish = publish  # type: ignore[method-assign]
    IngestPipeline(downloads=downloads, scanner=scanner, temp_root=tmp_path).ingest(
        binding=_binding(), source_name="private.bin", source=BytesIO(b"x")
    )
    assert observed["mode"] == 0o600


def test_infected_ingest_is_quarantined_and_never_published(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.ingest import IngestPipeline

    scanner = _Scanner("infected")
    downloads = _Downloads()
    pipeline = IngestPipeline(downloads=downloads, scanner=scanner, temp_root=tmp_path)
    receipt = pipeline.ingest(binding=_binding(), source_name="bad.exe", source=BytesIO(b"bad"))

    assert receipt.status == "quarantined"
    assert downloads.quarantine_calls[0]["binding"].principal_id == "owner-a@example.test"
    assert not downloads.publish_calls
    assert not list(tmp_path.iterdir())


def test_oversized_ingest_leaves_no_temp_files_and_does_not_call_scanner(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.ingest import IngestPipeline

    scanner = _Scanner()
    downloads = _Downloads()
    pipeline = IngestPipeline(downloads=downloads, scanner=scanner, temp_root=tmp_path, max_bytes=4)
    with pytest.raises(Exception, match="size"):
        pipeline.ingest(binding=_binding(), source_name="large.bin", source=BytesIO(b"12345"))
    assert not scanner.calls
    assert not downloads.publish_calls
    assert not downloads.quarantine_calls
    assert not list(tmp_path.iterdir())


def test_browser_completion_event_cannot_choose_another_owner(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.ingest import IngestPipeline

    scanner = _Scanner()
    downloads = _Downloads()
    pipeline = IngestPipeline(downloads=downloads, scanner=scanner, temp_root=tmp_path)
    with pytest.raises(TypeError):
        pipeline.ingest(
            binding=_binding(),
            source_name="x.txt",
            source=BytesIO(b"x"),
            principal_id="owner-b@example.test",
        )
