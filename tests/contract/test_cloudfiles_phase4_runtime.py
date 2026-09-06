"""Phase 4 production runtime wiring: build_app/entrypoint object graph.

The production runtime must construct and expose the operational components
with fail-closed safe defaults while the gateway page actions stay unchanged:

- ``ClamAvScanner`` (clamd INSTREAM over TCP) with the production defaults
  127.0.0.1:3310, 10 s timeout, 1 GiB cap, 64 KiB chunks;
- ``RetentionJanitor`` defaulting to 90 days;
- bounded ``Metrics`` that never store identity or filenames;
- an erasure hook bound to the durable store root that emits redacted audit
  events;
- a redacted quarantine notification hook (threat T14) that never raises;
- idempotent lifecycle cleanup on the runtime and in the entrypoint.

The assembly lives in ``cloudbrowser.cloudfiles.runtime`` and is consumed by
``cloudbrowser.cloudfiles_entrypoint``.
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

import pytest


def _serve(app):
    class QuietHandler(WSGIRequestHandler):
        def log_message(self, *args):
            return

    server = WSGIServer(("127.0.0.1", 0), QuietHandler)
    server.set_app(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _request(server, path, headers=None):
    connection = HTTPConnection(*server.server_address, timeout=3)
    connection.request("GET", path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    result = response.status, dict(response.getheaders()), body
    connection.close()
    return result


def _runtime_kwargs(**overrides):
    kwargs = {
        "downloads_base_url": "http://downloads:8083",
        "shared_secret": "s" * 32,
        "instance_id": "cloudfiles-test",
        "release_version": "0.2.0-test",
    }
    kwargs.update(overrides)
    return kwargs


def test_production_runtime_wires_clamav_scanner_with_safe_defaults():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    runtime = create_cloudfiles_runtime(**_runtime_kwargs(dev_store=True))
    scanner = runtime.scanner
    assert type(scanner).__name__ == "ClamAvScanner"
    assert scanner.host == "127.0.0.1"
    assert scanner.port == 3310
    assert scanner.timeout_s == 10.0
    assert scanner.max_bytes == 1024 * 1024 * 1024
    assert scanner.chunk_bytes == 64 * 1024


def test_production_runtime_wires_retention_janitor_with_90_day_default():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    runtime = create_cloudfiles_runtime(**_runtime_kwargs(dev_store=True))
    assert type(runtime.janitor).__name__ == "RetentionJanitor"
    assert runtime.janitor.retention_days == 90


def test_production_runtime_wires_metrics_that_never_store_identity():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    runtime = create_cloudfiles_runtime(**_runtime_kwargs(dev_store=True))
    runtime.metrics.record_ingest(
        principal="owner-a@example.test", filename="secret.pdf", size=12
    )
    assert runtime.metrics.snapshot() == {"ingest_count": 1, "bytes_ingested": 12}
    assert "owner-a@example.test" not in str(runtime.metrics.snapshot())
    assert "secret.pdf" not in str(runtime.metrics.snapshot())


def test_production_runtime_erasure_removes_durable_area_and_emits_redacted_audit(
    tmp_path,
):
    from io import BytesIO

    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime
    from cloudbrowser.downloads.contracts import PrincipalIdentity
    from cloudbrowser.downloads.service import DownloadsService

    store_root = tmp_path / "volume"
    service = DownloadsService(store_root=store_root)
    identity = PrincipalIdentity(
        request_id="req-1",
        principal_id="owner-a@example.test",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-1",
    )
    service.ingest(identity, "report.pdf", BytesIO(b"%PDF-1.4 owner-a"))

    runtime = create_cloudfiles_runtime(
        **_runtime_kwargs(store_root=store_root)
    )
    event = runtime.erase(principal="owner-a@example.test", request_id="req-erase")

    assert not service.list_files(identity).entries
    assert event["event_code"] == "erasure.completed"
    assert event["principal_hash"]
    assert "owner-a@example.test" not in str(event)


def test_production_runtime_quarantine_notifier_emits_only_redacted_fields():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    emitted = []

    class RecordingLogger:
        def warning(self, message, *args):
            emitted.append((message, args))

    runtime = create_cloudfiles_runtime(
        **_runtime_kwargs(
            notifier_logger=RecordingLogger(),
            dev_store=True,
        )
    )
    runtime.notifier.notify_quarantine(
        event={
            "request_id": "request-q",
            "principal": "owner-a@example.test",
            "name": "bad.exe",
            "size": 4,
        }
    )
    assert len(emitted) == 1
    blob = str(emitted[0])
    assert "owner-a@example.test" not in blob
    assert "bad.exe" not in blob


def test_production_runtime_quarantine_notifier_never_raises():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    class ExplodingLogger:
        def warning(self, message, *args):
            raise RuntimeError("logger unavailable")

    runtime = create_cloudfiles_runtime(
        **_runtime_kwargs(
            notifier_logger=ExplodingLogger(),
            dev_store=True,
        )
    )
    runtime.notifier.notify_quarantine(
        event={
            "request_id": "request-q",
            "principal": "owner-a@example.test",
            "name": "bad.exe",
            "size": 4,
        }
    )


def test_production_runtime_refuses_unsafe_configuration():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    with pytest.raises(ValueError):
        create_cloudfiles_runtime(**_runtime_kwargs(retention_days=0, dev_store=True))
    with pytest.raises(ValueError):
        create_cloudfiles_runtime(**_runtime_kwargs(retention_days=-1, dev_store=True))
    with pytest.raises(ValueError):
        create_cloudfiles_runtime(**_runtime_kwargs(scanner_timeout_s=0, dev_store=True))


def test_production_runtime_close_is_idempotent_lifecycle_cleanup():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    runtime = create_cloudfiles_runtime(**_runtime_kwargs(dev_store=True))
    runtime.close()
    runtime.close()  # second close must be a harmless no-op


def test_production_runtime_app_page_actions_stay_fail_closed():
    from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

    runtime = create_cloudfiles_runtime(**_runtime_kwargs(dev_store=True))
    server, thread = _serve(runtime.app)
    try:
        status, headers, body = _request(server, "/health")
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        payload = json.loads(body)
        assert payload == {
            "status": "ok",
            "component": "cloudfiles",
            "instance": "cloudfil",
        }
        status, _, body = _request(
            server,
            "/api/files",
            {"Remote-Email": "victim@example.test", "X-CB-Principal": "victim"},
        )
        assert status == 401
        assert b"victim@example.test" not in body
        assert b"victim" not in body
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_entrypoint_builds_runtime_and_cleans_up_server_and_runtime(monkeypatch):
    import cloudbrowser.cloudfiles_entrypoint as entrypoint

    captured = {}
    closed = {"server": False, "runtime": False}

    class FakeRuntime:
        app = object()

        def close(self):
            closed["runtime"] = True

    def fake_create_runtime(**kwargs):
        captured.update(kwargs)
        return FakeRuntime()

    class FakeServer:
        def serve_forever(self):
            captured["served"] = True

        def server_close(self):
            closed["server"] = True

    monkeypatch.setenv("CB_DOWNLOADS_BASE_URL", "http://downloads:8083")
    monkeypatch.setenv("CB_DOWNLOADS_SHARED_SECRET", "s" * 32)
    monkeypatch.setenv("CB_INSTANCE_ID", "cloudfiles-test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "0.2.0-test")
    monkeypatch.delenv("CB_EDGE_AUTH", raising=False)
    monkeypatch.setattr(
        entrypoint, "create_cloudfiles_runtime", fake_create_runtime
    )
    monkeypatch.setattr(
        entrypoint, "make_server", lambda host, port, app: FakeServer()
    )

    entrypoint.main()

    assert captured["downloads_base_url"] == "http://downloads:8083"
    assert captured["shared_secret"] == "s" * 32
    assert captured["instance_id"] == "cloudfiles-test"
    assert captured["release_version"] == "0.2.0-test"
    assert captured["served"] is True
    assert closed["server"] is True
    assert closed["runtime"] is True
