"""Phase 4 lifecycle contracts on the durable per-owner store.

Covers the frozen CloudFiles operational guarantees (product requirement §5):
- 5 GB per-principal quota enforcement before publication (threat T9);
- 90-day retention purge (threat T9), quarantine untouched;
- GDPR erasure of every owner layout, idempotently (threat T10);
- bounded usage accounting used by quota and metrics;
- redacted audit results for purge and erasure (threat T14).
"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

import pytest

from cloudbrowser.downloads.store import (
    DownloadStore,
    owner_key,
)


def _ingest(store: DownloadStore, principal: str, name: str, payload: bytes) -> None:
    store.ingest(principal, name, BytesIO(payload))


def test_usage_bytes_counts_only_regular_entries(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    _ingest(store, "owner-a", "a.txt", b"12345")
    _ingest(store, "owner-a", "b.txt", b"123456789")
    assert store.usage_bytes("owner-a") == 14
    assert store.usage_bytes("owner-b") == 0


def test_ingest_enforces_per_principal_quota(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path, quota_bytes=10)
    _ingest(store, "owner-a", "a.txt", b"12345")
    with pytest.raises(ValueError):
        _ingest(store, "owner-a", "b.txt", b"123456")
    # The oversized file must not exist and usage must be unchanged.
    assert store.read("owner-a", "b.txt") is None
    assert store.usage_bytes("owner-a") == 5
    # Another principal is unaffected by owner-a's quota.
    _ingest(store, "owner-b", "c.txt", b"1234567890")
    assert store.usage_bytes("owner-b") == 10


def test_purge_removes_only_expired_entries(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    _ingest(store, "owner-a", "old.pdf", b"old")
    _ingest(store, "owner-a", "new.pdf", b"new")
    entries = tmp_path / owner_key("owner-a") / "entries"
    old_file = entries / "old.pdf"
    now = 2_000_000_000
    os.utime(old_file, (now - 200, now - 200))
    os.utime(entries / "new.pdf", (now, now))
    removed = store.purge("owner-a", older_than_ts=now - 100)
    assert removed == ["old.pdf"]
    assert store.read("owner-a", "old.pdf") is None
    assert store.read("owner-a", "new.pdf") == b"new"


def test_purge_never_touches_quarantine(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    store.quarantine("owner-a", "bad.exe", BytesIO(b"bad"))
    qdir = tmp_path / owner_key("owner-a") / "quarantine"
    qfile = qdir / "bad.exe"
    now = 2_000_000_000
    os.utime(qfile, (now - 200, now - 200))
    removed = store.purge("owner-a", older_than_ts=now - 100)
    assert removed == []
    assert qfile.is_file()


def test_erase_removes_hashed_and_prior_layouts(tmp_path: Path) -> None:
    # Prior layout: raw principal dir with files (compatibility reads).
    prior = tmp_path / "owner-a"
    prior.mkdir()
    (prior / "legacy.pdf").write_bytes(b"legacy")
    store = DownloadStore(tmp_path)
    _ingest(store, "owner-a", "current.pdf", b"current")
    assert (tmp_path / owner_key("owner-a") / "entries" / "current.pdf").is_file()
    assert store.read("owner-a", "legacy.pdf") == b"legacy"

    store.erase("owner-a")
    assert not (tmp_path / owner_key("owner-a")).exists()
    assert not prior.exists()
    assert store.list_entries("owner-a") == []


def test_erase_is_idempotent_and_safe_for_missing_owner(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    store.erase("never-seen")  # must not raise
    store.erase("never-seen")
    _ingest(store, "owner-b", "keep.pdf", b"keep")
    store.erase("owner-b")
    store.erase("owner-b")
    assert store.list_entries("owner-b") == []


def test_erase_never_follows_symlinks(tmp_path: Path) -> None:
    store = DownloadStore(tmp_path)
    _ingest(store, "owner-a", "real.pdf", b"real")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    entries = tmp_path / owner_key("owner-a") / "entries"
    (entries / "link.pdf").symlink_to(outside)
    store.erase("owner-a")
    assert outside.read_bytes() == b"outside"


def test_purge_results_are_redacted_for_audit(tmp_path: Path) -> None:
    from cloudbrowser.cloudfiles.audit import redact_event
    from cloudbrowser.cloudfiles.retention import purge_summary

    store = DownloadStore(tmp_path)
    _ingest(store, "owner-a", "secret.pdf", b"x")
    entries = tmp_path / owner_key("owner-a") / "entries"
    os.utime(entries / "secret.pdf", (1, 1))
    removed = store.purge("owner-a", older_than_ts=1000)
    event = purge_summary(removed)
    assert event == {"purged_count": 1}
    assert "secret.pdf" not in str(redact_event({"purged": removed}))


def test_service_sweep_and_erasure_survive_restart(tmp_path: Path) -> None:
    """Operational facade: a new service instance (restart) sees the effects
    of retention purge and GDPR erasure on the durable volume."""
    from datetime import datetime, timedelta, timezone

    from cloudbrowser.downloads.service import DownloadsService

    ident = _identity()
    service = DownloadsService(store_root=tmp_path)
    service.ingest(ident, "old.pdf", BytesIO(b"old"))
    service.ingest(ident, "fresh.pdf", BytesIO(b"fresh"))
    entries = tmp_path / owner_key("owner-a") / "entries"
    past = datetime.now(timezone.utc) - timedelta(days=400)
    os.utime(entries / "old.pdf", (past.timestamp(), past.timestamp()))

    removed = service.purge_expired(
        "owner-a", older_than=datetime.now(timezone.utc) - timedelta(days=90)
    )
    assert removed == ["old.pdf"]

    service.erase("owner-a")
    # A fresh instance (restart) observes the erased durable state.
    again = DownloadsService(store_root=tmp_path)
    assert again.list_files(ident).entries == ()
    assert again.usage_bytes("owner-a") == 0


def _identity():
    from cloudbrowser.downloads.contracts import PrincipalIdentity

    return PrincipalIdentity(
        request_id="request-a",
        principal_id="owner-a",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-1",
    )
