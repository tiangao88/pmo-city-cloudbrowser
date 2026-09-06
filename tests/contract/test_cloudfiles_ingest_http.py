"""Internal CloudFiles ingest receiver contract tests (RED first).

The receiver is the cloudfiles-side half of the production browser-download
transport: an internal authenticated HTTP endpoint that accepts a bounded
file stream from the browser service and publishes it through the existing
``IngestPipeline`` (stage -> scan -> DownloadsPort).

Invariants under test:
- a completed stream is published and durably persisted for its owner only;
- the trusted secret is required (except ``GET /health``);
- Content-Length larger than the configured cap is rejected before reading;
- a body larger than its declared Content-Length is never over-read;
- unsafe names are rejected; the binding comes only from allowlisted headers;
- duplicate names are safely suffixed, never overwritten;
- infected streams are quarantined and never retrievable;
- responses never leak the raw principal or any server path;
- the server shuts down cleanly.
"""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

from cloudbrowser.downloads.contracts import PrincipalIdentity, ServerIdentity
from cloudbrowser.downloads.service import DownloadsService

SECRET = "contract-secret-0123456789abcdef"


def _identity(principal: str) -> PrincipalIdentity:
    return PrincipalIdentity(
        request_id="request-a",
        principal_id=principal,
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
    )


def _headers(secret: str = SECRET, *, principal: str = "owner-a@example.test", name: str = "report.pdf") -> dict[str, str]:
    return {
        "X-CB-Trusted-Secret": secret,
        "X-CB-Principal": principal,
        "X-CB-Profile": "profile-a",
        "X-CB-Browser": "browser-a",
        "X-CB-Generation": "generation-a",
        "X-CB-Request-Id": "request-a",
        "X-CB-Filename": name,
    }


def _start(tmp_path: Path, *, scanner=None, max_bytes: int = 1024 * 1024):
    from cloudbrowser.cloudfiles.downloads_adapter import DownloadsStoreAdapter
    from cloudbrowser.cloudfiles.ingest import IngestPipeline
    from cloudbrowser.cloudfiles.ingest_api import create_ingest_server
    from cloudbrowser.cloudfiles.scanner import CleanScanner

    service = DownloadsService(store_root=tmp_path / "store")
    pipeline = IngestPipeline(
        downloads=DownloadsStoreAdapter(service),
        scanner=scanner or CleanScanner(),
        temp_root=tmp_path / "staging",
    )
    server = create_ingest_server(
        pipeline,
        server_identity=ServerIdentity("cloudfiles-ingest", "contract"),
        trusted_secret=SECRET.encode("utf-8"),
        address=("127.0.0.1", 0),
        max_bytes=max_bytes,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return service, server, thread


def _stop(server, thread) -> None:
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


def _request(server, method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    result = (response.status, data)
    connection.close()
    return result


def test_completed_stream_is_published_and_persisted_for_its_owner(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path)
    try:
        status, body = _request(server, "POST", "/ingest/complete", body=b"payload", headers=_headers())

        assert status == 200
        payload = json.loads(body)
        assert payload["name"] == "report.pdf"
        assert payload["size"] == 7
        assert payload["status"] == "published"
        assert payload["request_id"] == "request-a"
        assert len(payload["sha256"]) == 64

        assert service.read_file(_identity("owner-a@example.test"), "report.pdf") == b"payload"
        assert service.read_file(_identity("owner-b@example.test"), "report.pdf") is None
        assert not list((tmp_path / "staging").iterdir())
    finally:
        _stop(server, thread)


def test_trusted_secret_is_required_and_health_is_open(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path)
    try:
        status, _ = _request(server, "POST", "/ingest/complete", body=b"payload", headers=_headers(secret="wrong-secret-value-0000"))
        assert status == 401
        status, _ = _request(server, "POST", "/ingest/complete", body=b"payload", headers={k: v for k, v in _headers().items() if k != "X-CB-Trusted-Secret"})
        assert status == 401
        status, body = _request(server, "GET", "/health")
        assert status == 200
        assert json.loads(body)["status"] == "ok"
        status, _ = _request(server, "POST", "/ingest/nope", body=b"x", headers=_headers())
        assert status == 404
    finally:
        _stop(server, thread)


def test_oversized_content_length_is_rejected_before_reading(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path, max_bytes=4)
    try:
        status, body = _request(server, "POST", "/ingest/complete", body=b"12345", headers=_headers())
        assert status == 413
        assert b"too_large" in body
        assert service.read_file(_identity("owner-a@example.test"), "report.pdf") is None
        staging = tmp_path / "staging"
        assert not staging.exists() or not list(staging.iterdir())
    finally:
        _stop(server, thread)


def test_body_never_reads_past_declared_content_length(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path, max_bytes=64)
    try:
        headers = _headers()
        headers["Content-Length"] = "2"
        status, body = _request(server, "POST", "/ingest/complete", body=b"payload", headers=headers)
        assert status == 200
        payload = json.loads(body)
        assert payload["size"] == 2
        assert service.read_file(_identity("owner-a@example.test"), "report.pdf") == b"pa"
    finally:
        _stop(server, thread)


def test_unsafe_names_are_rejected(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path)
    try:
        for name in ("../evil.pdf", ".hidden", "sub/x.txt", "a\x00b"):
            status, body = _request(
                server, "POST", "/ingest/complete", body=b"x", headers=_headers(name=name)
            )
            assert status == 400, name
            assert b"invalid_name" in body, name
        assert service.list_files(_identity("owner-a@example.test")).entries == ()
    finally:
        _stop(server, thread)


def test_duplicate_names_are_safely_suffixed_never_overwritten(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path)
    try:
        status, body = _request(server, "POST", "/ingest/complete", body=b"first", headers=_headers())
        assert json.loads(body)["name"] == "report.pdf"
        status, body = _request(server, "POST", "/ingest/complete", body=b"second", headers=_headers())
        assert status == 200
        assert json.loads(body)["name"] == "report (1).pdf"

        assert service.read_file(_identity("owner-a@example.test"), "report.pdf") == b"first"
        assert service.read_file(_identity("owner-a@example.test"), "report (1).pdf") == b"second"
    finally:
        _stop(server, thread)


def test_infected_stream_is_quarantined_and_never_retrievable(tmp_path: Path) -> None:
    class Infected:
        def scan(self, path: Path, *, request_id: str) -> str:
            return "infected"

    service, server, thread = _start(tmp_path, scanner=Infected())
    try:
        status, body = _request(server, "POST", "/ingest/complete", body=b"MZ-bad", headers=_headers(name="bad.exe"))
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "quarantined"
        assert service.read_file(_identity("owner-a@example.test"), "bad.exe") is None
        entries = service.list_files(_identity("owner-a@example.test")).entries
        assert entries and entries[0].quarantined is True
    finally:
        _stop(server, thread)


def test_responses_never_contain_principal_or_server_paths(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path, max_bytes=4)
    try:
        status, body = _request(server, "POST", "/ingest/complete", body=b"ok", headers=_headers())
        assert status == 200
        assert b"owner-a@example.test" not in body
        assert b"staging" not in body
        assert b"store" not in body

        status, body = _request(server, "POST", "/ingest/complete", body=b"12345", headers=_headers())
        assert status == 413
        assert b"owner-a@example.test" not in body
        assert b"staging" not in body
    finally:
        _stop(server, thread)


def test_binding_comes_only_from_allowlisted_headers(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path)
    try:
        headers = _headers()
        headers.pop("X-CB-Principal")
        status, body = _request(server, "POST", "/ingest/complete", body=b"x", headers=headers)
        assert status == 400
        assert b"invalid_binding" in body

        headers = _headers()
        headers.pop("X-CB-Principal")
        headers["Remote-Email"] = "owner-b@example.test"
        status, _ = _request(server, "POST", "/ingest/complete", body=b"x", headers=headers)
        assert status == 400, "Remote-Email must never select an owner"

        status, body = _request(server, "POST", "/ingest/complete", body=b"x", headers=_headers(principal="bad/../value"))
        assert status == 400
        assert b"invalid_binding" in body
        assert service.list_files(_identity("owner-a@example.test")).entries == ()
    finally:
        _stop(server, thread)


def test_server_shuts_down_cleanly(tmp_path: Path) -> None:
    service, server, thread = _start(tmp_path)
    try:
        _request(server, "POST", "/ingest/complete", body=b"payload", headers=_headers())
    finally:
        _stop(server, thread)
    assert service.read_file(_identity("owner-a@example.test"), "report.pdf") == b"payload"
