"""Phase 4 operational policy tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_retention_janitor_selects_expired_entries_without_deleting(tmp_path: Path):
    from cloudbrowser.cloudfiles.retention import RetentionJanitor

    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    selected = RetentionJanitor(retention_days=90, clock=lambda: now).expired_entries(
        [
            {"name": "old.pdf", "mtime": now - timedelta(days=91)},
            {"name": "new.pdf", "mtime": now - timedelta(days=1)},
        ]
    )
    assert selected == ["old.pdf"]


def test_quarantine_maps_only_exact_clean_to_publication():
    from cloudbrowser.cloudfiles.quarantine import scan_verdict

    assert scan_verdict("clean") == "published"
    assert scan_verdict("infected") == "quarantined"
    assert scan_verdict("scanner_error") == "quarantined"


def test_erasure_is_redacted(tmp_path: Path):
    from cloudbrowser.cloudfiles.erasure import erase_principal

    result = erase_principal(
        principal="owner-a@example.test", store_root=tmp_path, request_id="request-a"
    )
    assert result["event_code"] == "erasure.completed"
    assert result["principal_hash"]
    assert "owner-a@example.test" not in str(result)


def test_metrics_never_store_identity_or_filename():
    from cloudbrowser.cloudfiles.metrics import Metrics

    metrics = Metrics()
    metrics.record_ingest(principal="owner-a@example.test", filename="secret.pdf", size=12)
    assert metrics.snapshot() == {"ingest_count": 1, "bytes_ingested": 12}
    assert "owner-a@example.test" not in str(metrics.snapshot())
    assert "secret.pdf" not in str(metrics.snapshot())
