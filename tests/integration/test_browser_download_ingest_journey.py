"""End-to-end browser-download ingest transport journey (RED first).

Real handoff + persistence: the browser-side watcher reads a server-configured
download directory (Chromium-style: completed files plus `.crdownload`
partials), emits only completed files through the typed ingest client over
real HTTP, the internal CloudFiles ingest receiver feeds the existing
scan-before-publish pipeline, and the durable owner store is written on disk
and survives a fresh service instance (restart/recreate persistence).
"""

from __future__ import annotations

import threading
from pathlib import Path

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.downloads.contracts import PrincipalIdentity, ServerIdentity
from cloudbrowser.downloads.service import DownloadsService

SECRET = "journey-secret-0123456789abcdef"


def _binding() -> PrincipalBinding:
    return PrincipalBinding(
        principal_id="owner-a@example.test",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
    )


def _identity(principal: str) -> PrincipalIdentity:
    return PrincipalIdentity(
        request_id="request-journey",
        principal_id=principal,
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
    )


def _start_ingest(store_root: Path, staging: Path):
    from cloudbrowser.cloudfiles.downloads_adapter import DownloadsStoreAdapter
    from cloudbrowser.cloudfiles.ingest import IngestPipeline
    from cloudbrowser.cloudfiles.ingest_api import create_ingest_server
    from cloudbrowser.cloudfiles.scanner import CleanScanner

    service = DownloadsService(store_root=store_root)
    pipeline = IngestPipeline(
        downloads=DownloadsStoreAdapter(service),
        scanner=CleanScanner(),
        temp_root=staging,
    )
    server = create_ingest_server(
        pipeline,
        server_identity=ServerIdentity("cloudfiles-ingest", "journey"),
        trusted_secret=SECRET.encode("utf-8"),
        address=("127.0.0.1", 0),
        max_bytes=1024,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return service, server, thread


def test_browser_download_handoff_publishes_and_persists_across_restart(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import (
        BrowserDownloadWatcher,
        DownloadWatchConfig,
    )
    from cloudbrowser.cloudfiles.ingest_client import IngestClient

    store_root = tmp_path / "store"
    service, server, thread = _start_ingest(store_root, tmp_path / "staging")
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"must-stay-outside")

    (download_dir / "report.pdf").write_bytes(b"%PDF-1.4 owner-a report")
    (download_dir / "invoice.pdf.crdownload").write_bytes(b"partial")
    (download_dir / "link.pdf").symlink_to(outside)

    client = IngestClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        shared_secret=SECRET,
    )
    watcher = BrowserDownloadWatcher(
        DownloadWatchConfig(download_dir=download_dir, binding=_binding(), max_bytes=1024),
        submit=lambda event: client.submit(
            binding=event.binding,
            source_name=event.source_name,
            source=event.source,
            size=event.size,
        ),
    )
    try:
        receipts = watcher.emit_once()

        assert [receipt.name for receipt in receipts] == ["report.pdf"]
        assert receipts[0].status == "published"
        assert receipts[0].size == len(b"%PDF-1.4 owner-a report")
        assert not (download_dir / "report.pdf").exists(), "completed file consumed"
        assert (download_dir / "invoice.pdf.crdownload").exists(), "partial retained"
        assert outside.read_bytes() == b"must-stay-outside"
        assert service.read_file(_identity("owner-a@example.test"), "link.pdf") is None

        assert service.read_file(_identity("owner-a@example.test"), "report.pdf") == b"%PDF-1.4 owner-a report"
        assert service.read_file(_identity("owner-b@example.test"), "report.pdf") is None
        assert not list((tmp_path / "staging").iterdir())

        text = str(receipts[0])
        assert "owner-a@example.test" not in text
        assert str(download_dir) not in text
        assert str(store_root) not in text

        # Restart/recreate: a fresh service on the same durable volume still
        # serves the owner area.
        fresh = DownloadsService(store_root=store_root)
        assert fresh.read_file(_identity("owner-a@example.test"), "report.pdf") == b"%PDF-1.4 owner-a report"
        assert fresh.read_file(_identity("owner-b@example.test"), "report.pdf") is None
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        watcher.close()


def test_handoff_retry_and_safe_duplicates_over_real_http(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import (
        BrowserDownloadWatcher,
        DownloadWatchConfig,
    )
    from cloudbrowser.cloudfiles.ingest_client import IngestClient

    store_root = tmp_path / "store"
    service, server, thread = _start_ingest(store_root, tmp_path / "staging")
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    client = IngestClient(
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        shared_secret=SECRET,
    )
    attempts = {"count": 0}

    def submit(event):
        if event.source_name == "report.pdf":
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("first attempt fails")
        return client.submit(
            binding=event.binding,
            source_name=event.source_name,
            source=event.source,
            size=event.size,
        )

    watcher = BrowserDownloadWatcher(
        DownloadWatchConfig(download_dir=download_dir, binding=_binding(), max_bytes=1024),
        submit=submit,
    )
    try:
        (download_dir / "report.pdf").write_bytes(b"first")
        (download_dir / "later.txt").write_bytes(b"later")

        # First scan: report.pdf's submit fails (kept for retry) while the
        # rest of the batch is still processed.
        receipts = watcher.emit_once()
        assert [receipt.name for receipt in receipts] == ["later.txt"]
        assert (download_dir / "report.pdf").exists(), "failed handoff keeps the file"
        assert not (download_dir / "later.txt").exists()

        # Second scan: the retried handoff succeeds and consumes the file.
        receipts = watcher.emit_once()
        assert [receipt.name for receipt in receipts] == ["report.pdf"]
        assert not (download_dir / "report.pdf").exists()

        # A second completed download with the same name is a safe duplicate,
        # never an overwrite.
        (download_dir / "report.pdf").write_bytes(b"second")
        receipts = watcher.emit_once()
        assert [receipt.name for receipt in receipts] == ["report (1).pdf"]

        assert service.read_file(_identity("owner-a@example.test"), "report.pdf") == b"first"
        assert service.read_file(_identity("owner-a@example.test"), "report (1).pdf") == b"second"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        watcher.close()
