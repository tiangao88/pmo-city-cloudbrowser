"""Phase 2 integration contracts for browser completion and downloads."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.downloads_client import DownloadsClient, DownloadsClientError
from cloudbrowser.cloudfiles.ingest import IngestPipeline


def binding(principal: str = "owner-a@example.test") -> PrincipalBinding:
    return PrincipalBinding(
        principal_id=principal,
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
        request_id="request-a",
    )


def test_real_downloads_store_adapter_publishes_and_reads_only_binding_owner(tmp_path: Path) -> None:
    from cloudbrowser.downloads.service import DownloadsService
    from cloudbrowser.cloudfiles.downloads_adapter import DownloadsStoreAdapter

    adapter = DownloadsStoreAdapter(DownloadsService(store_root=tmp_path))
    receipt = adapter.publish(
        binding=binding(), source_name="report.pdf", source=BytesIO(b"payload"),
        size=7, sha256="".join("a" for _ in range(64)),
    )
    assert receipt.name == "report.pdf"
    assert adapter.list_files(binding=binding())["entries"][0]["name"] == "report.pdf"
    assert adapter.read_file(binding=binding(), name="report.pdf") == b"payload"
    assert adapter.read_file(binding=binding("owner-b@example.test"), name="report.pdf") is None


def test_clean_pipeline_is_streamed_to_store_and_temp_is_removed(tmp_path: Path) -> None:
    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            assert path.exists()
            assert request_id == "request-a"
            return "clean"

    class Downloads:
        def __init__(self) -> None:
            self.receipts = []

        def publish(self, *, binding, source_name, source, size, sha256):
            self.receipts.append((binding, source_name, source.read(), size, sha256))
            return SimpleNamespace(name=source_name, sha256=sha256)

        def quarantine(self, **kwargs):
            raise AssertionError("clean content cannot be quarantined")

    downloads = Downloads()
    result = IngestPipeline(downloads=downloads, scanner=Scanner(), temp_root=tmp_path).ingest(
        binding=binding(), source_name="report.pdf", source=BytesIO(b"payload")
    )
    assert result.status == "published"
    assert downloads.receipts[0][0] == binding()
    assert downloads.receipts[0][2] == b"payload"
    assert not list(tmp_path.iterdir())


def test_scanner_failure_fails_closed_without_publish_or_quarantine(tmp_path: Path) -> None:
    class Scanner:
        def scan(self, path: Path, *, request_id: str) -> str:
            raise RuntimeError("scanner unavailable")

    class Downloads:
        def publish(self, **kwargs):
            raise AssertionError

        def quarantine(self, **kwargs):
            raise AssertionError

    with pytest.raises(RuntimeError, match="scanner unavailable"):
        IngestPipeline(downloads=Downloads(), scanner=Scanner(), temp_root=tmp_path).ingest(
            binding=binding(), source_name="x.txt", source=BytesIO(b"x")
        )
    assert not list(tmp_path.iterdir())


def test_client_rejects_invalid_secret_and_bounds_paths() -> None:
    with pytest.raises(ValueError):
        DownloadsClient(base_url="http://downloads:8083", shared_secret="short")
    client = DownloadsClient(base_url="http://downloads:8083", shared_secret="s" * 32)
    with pytest.raises(ValueError):
        client._request(path="/api/files?owner=other", binding=binding(), request_id="request-a")


def test_client_timeout_and_http_failure_are_bounded(monkeypatch) -> None:
    client = DownloadsClient(base_url="http://downloads:8083", shared_secret="s" * 16, timeout_s=0.5)

    def fail(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr("cloudbrowser.cloudfiles.downloads_client.urlopen", fail)
    with pytest.raises(DownloadsClientError, match="dependency unavailable"):
        client.list_files(binding=binding(), request_id="request-a")


def test_client_does_not_accept_public_identity_headers() -> None:
    client = DownloadsClient(base_url="http://downloads:8083", shared_secret="s" * 16)
    headers = client.headers(binding(), request_id="request-b")
    assert "Remote-Email" not in headers
    assert "X-CB-Owner" not in headers
    assert headers["X-CB-Principal"] == "owner-a@example.test"
