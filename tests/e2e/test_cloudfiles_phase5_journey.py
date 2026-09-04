"""Phase 5 local end-to-end qualification: the complete employee journey.

Journey under test (spec 91 Phase 5):

    CloudBrowser download (fake completion event)
      -> ingest (scan-before-publish pipeline)
      -> durable owner area (downloads store on the shared volume)
      -> TinyAuth fixture (server-validated session)
      -> CloudFiles gateway over real HTTP
      -> listing -> local attachment download

Plus the operational guarantees: multi-slot convergence, owner isolation,
restart/recreate persistence, quota, retention purge, GDPR erasure, and
quarantine (infected content is never listed or retrievable, and the
notification seam emits only bounded redacted events).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from io import BytesIO
import json
import os
from pathlib import Path
import threading
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.downloads.api import create_downloads_server
from cloudbrowser.downloads.contracts import PrincipalIdentity, ServerIdentity
from cloudbrowser.downloads.service import DownloadsService
from cloudbrowser.downloads.store import owner_key


SECRET = "e2e-shared-secret-0123456789abcdef"


# ---------------------------------------------------------------------------
# Local runtime helpers
# ---------------------------------------------------------------------------


def _start_downloads(root: Path, *, quota_bytes: int | None = None):
    service = DownloadsService(store_root=root, quota_bytes=quota_bytes)
    server = create_downloads_server(
        service,
        server_identity=ServerIdentity(component="downloads", instance_id="e2e"),
        trusted_secret=SECRET.encode("utf-8"),
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return service, server, thread


def _stop(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def _gateway(downloads_port: int):
    from cloudbrowser.cloudfiles.runtime import build_app

    return build_app(
        downloads_base_url=f"http://127.0.0.1:{downloads_port}",
        shared_secret=SECRET,
        instance_id="e2e-cloudfiles",
        release_version="0.2.0-dev1",
    )


def _session_app(app, subject: str):
    from cloudbrowser.cloudfiles.api import SESSION_ENVIRON_KEY
    from cloudbrowser.cloudfiles.identity import TinyAuthSession

    session = TinyAuthSession(subject=subject, request_id="req-e2e")

    def middleware(environ, start_response):
        environ[SESSION_ENVIRON_KEY] = session
        return app(environ, start_response)

    return middleware


def _serve(app):
    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            return

    server = WSGIServer(("127.0.0.1", 0), QuietHandler)
    server.set_app(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _http(server, path: str, headers: dict[str, str] | None = None):
    connection = HTTPConnection(*server.server_address, timeout=5)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = (response.status, dict(response.getheaders()), body)
    connection.close()
    return result


def _listing_names(server) -> list[str]:
    _, _, body = _http(server, "/api/files", {"Accept": "application/json"})
    return [entry["name"] for entry in json.loads(body)["entries"]]


def _pipeline(root: Path, *, scanner=None, notifier=None, quota_bytes=None):
    from cloudbrowser.cloudfiles.downloads_adapter import DownloadsStoreAdapter
    from cloudbrowser.cloudfiles.ingest import IngestPipeline
    from cloudbrowser.cloudfiles.scanner import CleanScanner

    # A separate service instance writes the shared volume, emulating the
    # browser/slot side of the ingest seam.
    adapter = DownloadsStoreAdapter(
        DownloadsService(store_root=root, quota_bytes=quota_bytes)
    )
    return IngestPipeline(
        downloads=adapter,
        scanner=scanner or CleanScanner(),
        temp_root=root / "staging",
        notifier=notifier,
    )


def _binding(principal: str, *, browser: str = "browser-1", generation: str = "generation-1") -> PrincipalBinding:
    return PrincipalBinding(
        principal_id=principal,
        request_id=f"req-{browser}-{generation}",
        profile_id="profile-e2e",
        browser_id=browser,
        generation=generation,
    )


def _identity(principal: str) -> PrincipalIdentity:
    return PrincipalIdentity(
        request_id="req-e2e-ident",
        principal_id=principal,
        profile_id="profile-e2e",
        browser_id="browser-1",
        generation="generation-1",
    )


def _download(source, binding: PrincipalBinding, name: str, payload: bytes):
    from cloudbrowser.cloudfiles.browser_downloads import BrowserDownloadCompleted

    source.complete(
        BrowserDownloadCompleted(binding=binding, source_name=name, source=BytesIO(payload))
    )


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def notify_quarantine(self, *, event: dict[str, object]) -> None:
        self.events.append(dict(event))


class _InfectedScanner:
    def scan(self, path: Path, *, request_id: str) -> str:
        return "infected"


# ---------------------------------------------------------------------------
# The journey
# ---------------------------------------------------------------------------


def test_phase5_employee_journey_isolation_convergence_and_restart(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import (
        FakeBrowserDownloadSource,
        connect_browser_downloads,
    )

    root = tmp_path / "volume"
    service, dl_server, dl_thread = _start_downloads(root)
    source = FakeBrowserDownloadSource()
    connect_browser_downloads(source, _pipeline(root))

    # Employee A downloads from two different slots (same durable area).
    _download(source, _binding("owner-a@example.test", browser="slot-1"), "report.pdf", b"%PDF-1.4 owner-a report")
    _download(
        source,
        _binding("owner-a@example.test", browser="slot-2", generation="generation-2"),
        "invoice.pdf",
        b"%PDF-1.4 owner-a invoice",
    )
    # Employee B's download lands only in B's area.
    _download(source, _binding("owner-b@example.test"), "secret.pdf", b"%PDF-1.4 owner-b")

    gateway = _gateway(dl_server.server_address[1])

    # Employee A: convergence of two slots, attachment download, no cross-owner file.
    server_a, thread_a = _serve(_session_app(gateway, "owner-a@example.test"))
    try:
        assert sorted(_listing_names(server_a)) == ["invoice.pdf", "report.pdf"]
        status, headers, body = _http(server_a, "/file/report.pdf")
        assert status == 200
        assert headers["Content-Disposition"].startswith("attachment")
        assert body == b"%PDF-1.4 owner-a report"
        status, _, _ = _http(server_a, "/file/secret.pdf")
        assert status == 404
    finally:
        _stop(server_a, thread_a)

    # Employee B sees only B's files.
    server_b, thread_b = _serve(_session_app(gateway, "owner-b@example.test"))
    try:
        assert _listing_names(server_b) == ["secret.pdf"]
    finally:
        _stop(server_b, thread_b)

    # Restart/recreate: a fresh downloads service on the same durable volume
    # still serves the owner area through a fresh gateway.
    _stop(dl_server, dl_thread)
    service2, dl_server2, dl_thread2 = _start_downloads(root)
    try:
        entries = service2.list_files(_identity("owner-a@example.test")).entries
        assert sorted(entry.name for entry in entries) == ["invoice.pdf", "report.pdf"]
        gateway2 = _gateway(dl_server2.server_address[1])
        server_c, thread_c = _serve(_session_app(gateway2, "owner-a@example.test"))
        try:
            assert sorted(_listing_names(server_c)) == ["invoice.pdf", "report.pdf"]
            _, _, body = _http(server_c, "/file/invoice.pdf")
            assert body == b"%PDF-1.4 owner-a invoice"
        finally:
            _stop(server_c, thread_c)
    finally:
        _stop(dl_server2, dl_thread2)


def test_phase5_quota_is_enforced_before_publication(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import (
        FakeBrowserDownloadSource,
        connect_browser_downloads,
    )

    root = tmp_path / "volume"
    service, dl_server, dl_thread = _start_downloads(root, quota_bytes=10)
    source = FakeBrowserDownloadSource()
    connect_browser_downloads(source, _pipeline(root, quota_bytes=10))
    binding = _binding("owner-a@example.test")

    _download(source, binding, "ok.txt", b"12345")
    with pytest.raises(ValueError):
        _download(source, binding, "too-big.txt", b"123456")

    assert service.usage_bytes("owner-a@example.test") == 5
    assert service.read_file(_identity("owner-a@example.test"), "too-big.txt") is None

    server, thread = _serve(_session_app(_gateway(dl_server.server_address[1]), "owner-a@example.test"))
    try:
        assert _listing_names(server) == ["ok.txt"]
    finally:
        _stop(server, thread)
        _stop(dl_server, dl_thread)


def test_phase5_retention_purge_and_gdpr_erasure(tmp_path: Path) -> None:
    root = tmp_path / "volume"
    service, dl_server, dl_thread = _start_downloads(root)
    ident = _identity("owner-a@example.test")
    service.ingest(ident, "old.pdf", BytesIO(b"old"))
    service.ingest(ident, "fresh.pdf", BytesIO(b"fresh"))
    # Age the old file past the 90-day retention window.
    old_path = root / owner_key("owner-a@example.test") / "entries" / "old.pdf"
    past = datetime.now(timezone.utc) - timedelta(days=400)
    os.utime(old_path, (past.timestamp(), past.timestamp()))

    removed = service.purge_expired(
        "owner-a@example.test",
        older_than=datetime.now(timezone.utc) - timedelta(days=90),
    )
    assert removed == ["old.pdf"]
    assert service.read_file(ident, "fresh.pdf") == b"fresh"

    # GDPR erasure through the facade removes everything durably and emits a
    # redacted audit event.
    from cloudbrowser.cloudfiles.erasure import erase_principal

    event = erase_principal(
        principal="owner-a@example.test",
        store_root=root,
        request_id="req-erase",
    )
    assert event["event_code"] == "erasure.completed"
    assert "owner-a@example.test" not in str(event)

    server, thread = _serve(_session_app(_gateway(dl_server.server_address[1]), "owner-a@example.test"))
    try:
        assert _listing_names(server) == []
        status, _, _ = _http(server, "/file/fresh.pdf")
        assert status == 404
    finally:
        _stop(server, thread)
        _stop(dl_server, dl_thread)


def test_phase5_quarantine_is_never_listed_or_served(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.browser_downloads import (
        FakeBrowserDownloadSource,
        connect_browser_downloads,
    )

    root = tmp_path / "volume"
    _, dl_server, dl_thread = _start_downloads(root)
    recorder = _Recorder()
    source = FakeBrowserDownloadSource()
    connect_browser_downloads(source, _pipeline(root, scanner=_InfectedScanner(), notifier=recorder))
    _download(source, _binding("owner-a@example.test"), "bad.exe", b"MZ-infected")

    # Bounded notification: hashes only, no raw identity or filename.
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert "owner-a@example.test" not in str(event)
    assert "bad.exe" not in str(event)

    server, thread = _serve(_session_app(_gateway(dl_server.server_address[1]), "owner-a@example.test"))
    try:
        assert _listing_names(server) == [], "quarantined names must not list"
        status, _, _ = _http(server, "/file/bad.exe")
        assert status == 404, "quarantined files must never be served"
    finally:
        _stop(server, thread)
        _stop(dl_server, dl_thread)
