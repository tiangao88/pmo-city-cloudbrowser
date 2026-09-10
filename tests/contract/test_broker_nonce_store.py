"""Durability, atomicity, and bounds for capability replay protection."""

from __future__ import annotations

import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore, NonceStoreFull


def _consume(store: DurableNonceStore, nonce: str = "nonce-a", *, now: int = 1000) -> bool:
    return store.consume(
        deployment="deployment-a",
        audience="credential-broker",
        nonce=nonce,
        expires_at=now + 30,
        now=now,
    )


def test_nonce_sqlite_lock_wait_obeys_shared_deadline(tmp_path: Path) -> None:
    path = tmp_path / "nonces.sqlite3"
    store = DurableNonceStore(path)
    blocker = sqlite3.connect(path, timeout=1.0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    deadline = BrokerDeadline(started + 0.1)
    try:
        with pytest.raises(BrokerDeadlineExceeded):
            store.consume(
                deployment="deployment-a",
                audience="credential-broker",
                nonce="nonce-deadline",
                expires_at=1030,
                now=1000,
                deadline=deadline,
            )
        assert time.monotonic() - started < 0.35
    finally:
        blocker.rollback()
        blocker.close()


def test_nonce_replay_is_rejected_after_store_restart(tmp_path: Path) -> None:
    path = tmp_path / "nonces.sqlite3"
    assert _consume(DurableNonceStore(path)) is True
    assert _consume(DurableNonceStore(path)) is False


def test_concurrent_nonce_consumption_has_exactly_one_winner(tmp_path: Path) -> None:
    store = DurableNonceStore(tmp_path / "nonces.sqlite3")
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: _consume(store), range(32)))
    assert results.count(True) == 1
    assert results.count(False) == 31


def test_store_key_includes_deployment_and_audience(tmp_path: Path) -> None:
    store = DurableNonceStore(tmp_path / "nonces.sqlite3")
    assert _consume(store) is True
    assert store.consume(
        deployment="deployment-b",
        audience="credential-broker",
        nonce="nonce-a",
        expires_at=1030,
        now=1000,
    ) is True
    assert store.consume(
        deployment="deployment-a",
        audience="other-broker",
        nonce="nonce-a",
        expires_at=1030,
        now=1000,
    ) is True


def test_store_fails_closed_at_bound_and_prunes_only_expired_rows(tmp_path: Path) -> None:
    store = DurableNonceStore(tmp_path / "nonces.sqlite3", max_records=2)
    assert store.consume(
        deployment="deployment-a",
        audience="credential-broker",
        nonce="soon-expired",
        expires_at=1001,
        now=1000,
    )
    assert _consume(store, "still-live")
    with pytest.raises(NonceStoreFull):
        _consume(store, "must-not-evict-live")
    assert store.consume(
        deployment="deployment-a",
        audience="credential-broker",
        nonce="after-prune",
        expires_at=1031,
        now=1001,
    )


def test_nonce_database_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "nonces.sqlite3"
    DurableNonceStore(path)
    assert os.stat(path).st_mode & 0o077 == 0
