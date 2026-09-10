"""Durable broker-operation idempotency contracts."""

from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.contracts import BrokerResult
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded
from cloudbrowser.credential_broker.idempotency import (
    DurableIdempotencyStore,
    IdempotencyStoreFull,
    OperationScope,
)


def _scope(**overrides: str) -> OperationScope:
    values = {
        "deployment": "deployment-a",
        "audience": "credential-broker",
        "operation": "credential.login",
        "profile_id": "profile-a",
        "principal_id": "principal-a",
        "browser_id": "browser-a",
        "generation": "generation-a",
        "site_id": "site-a",
        "target_tab_id": "target-a",
        "request_id": "request-a",
    }
    values.update(overrides)
    return OperationScope(**values)


def test_reserve_sqlite_lock_wait_obeys_shared_deadline(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.sqlite3"
    store = DurableIdempotencyStore(path)
    blocker = sqlite3.connect(path, timeout=1.0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    deadline = BrokerDeadline(started + 0.1)
    try:
        with pytest.raises(BrokerDeadlineExceeded):
            store.reserve(_scope(), deadline=deadline)
        assert time.monotonic() - started < 0.35
    finally:
        blocker.rollback()
        blocker.close()


def test_completed_result_replays_after_restart_without_secrets(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.sqlite3"
    owner = DurableIdempotencyStore(path)
    reservation = owner.reserve(_scope())
    assert reservation.acquired is True
    owner.complete(_scope(), reservation.owner_token, BrokerResult("request-a", "authenticated"))

    replay = DurableIdempotencyStore(path).reserve(_scope())
    assert replay.acquired is False
    assert replay.result == BrokerResult("request-a", "authenticated")
    assert "password" not in repr(replay).lower()
    assert "secret" not in repr(replay).lower()


def test_complete_operation_scope_prevents_cross_target_collisions(tmp_path: Path) -> None:
    store = DurableIdempotencyStore(tmp_path / "idempotency.sqlite3")
    first = store.reserve(_scope())
    second = store.reserve(_scope(target_tab_id="target-b"))
    assert first.acquired is True
    assert second.acquired is True


def test_concurrent_reservation_has_one_owner_and_waiters_replay_result(tmp_path: Path) -> None:
    store = DurableIdempotencyStore(tmp_path / "idempotency.sqlite3")
    entered = threading.Event()
    release = threading.Event()

    def operation() -> BrokerResult:
        entered.set()
        release.wait(timeout=5)
        return BrokerResult("request-a", "authenticated")

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(store.execute, _scope(), operation) for _ in range(12)]
        assert entered.wait(timeout=2)
        release.set()
        results = [future.result(timeout=5) for future in futures]

    assert results == [BrokerResult("request-a", "authenticated")] * 12


def test_duplicate_wait_obeys_shared_absolute_deadline_without_oversleeping(
    tmp_path: Path,
) -> None:
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    store = DurableIdempotencyStore(
        tmp_path / "idempotency.sqlite3",
        monotonic_clock=lambda: now[0],
        sleep=sleep,
        poll_interval_s=1.0,
    )
    assert store.reserve(_scope()).acquired is True
    deadline = BrokerDeadline(expires_at=100.25, monotonic_clock=lambda: now[0])

    with pytest.raises(BrokerDeadlineExceeded):
        store.execute(
            _scope(),
            lambda: pytest.fail("a duplicate waiter must not execute the operation"),
            deadline=deadline,
        )

    assert sleeps == [pytest.approx(0.25)]
    assert now[0] == pytest.approx(100.25)


def test_duplicate_wait_deadline_is_checked_before_reserve(
    tmp_path: Path,
) -> None:
    now = [100.0]
    store = DurableIdempotencyStore(
        tmp_path / "idempotency.sqlite3",
        monotonic_clock=lambda: now[0],
    )
    deadline = BrokerDeadline(expires_at=100.0, monotonic_clock=lambda: now[0])

    with pytest.raises(BrokerDeadlineExceeded):
        store.execute(
            _scope(),
            lambda: pytest.fail("an expired duplicate must not reserve or execute"),
            deadline=deadline,
        )

    assert store.reserve(_scope()).acquired is True


def test_failed_owner_is_replayed_as_unknown_outcome_and_not_retried(tmp_path: Path) -> None:
    store = DurableIdempotencyStore(tmp_path / "idempotency.sqlite3")

    def fail() -> BrokerResult:
        raise RuntimeError("sensitive programmer detail")

    try:
        store.execute(_scope(), fail)
    except RuntimeError:
        pass
    else:
        raise AssertionError("operation must raise")

    calls = 0

    def retry() -> BrokerResult:
        nonlocal calls
        calls += 1
        return BrokerResult("request-a", "authenticated")

    replay = store.execute(_scope(), retry)
    assert replay == BrokerResult("request-a", "failed", "unknown_outcome")
    assert calls == 0


def test_crashed_reservation_becomes_replayable_unknown_outcome_after_lease(
    tmp_path: Path,
) -> None:
    path = tmp_path / "idempotency.sqlite3"
    owner = DurableIdempotencyStore(path, reservation_lease_s=10, clock=lambda: 100)
    reservation = owner.reserve(_scope())
    assert reservation.acquired is True

    restarted = DurableIdempotencyStore(path, reservation_lease_s=10, clock=lambda: 111)
    replay = restarted.reserve(_scope())

    assert replay.acquired is False
    assert replay.result == BrokerResult("request-a", "failed", "unknown_outcome")
    assert restarted.reserve(_scope()).result == replay.result


def test_live_reservation_is_not_evicted_when_capacity_is_full(tmp_path: Path) -> None:
    store = DurableIdempotencyStore(
        tmp_path / "idempotency.sqlite3",
        max_records=1,
        reservation_lease_s=10,
        clock=lambda: 100,
    )
    owner = store.reserve(_scope())
    assert owner.acquired is True

    with pytest.raises(IdempotencyStoreFull):
        store.reserve(_scope(request_id="request-b"))

    assert store.reserve(_scope()).acquired is False
    assert store.reserve(_scope()).result is None


def test_expired_reservation_is_converted_before_capacity_is_reused(tmp_path: Path) -> None:
    now = [100]
    path = tmp_path / "idempotency.sqlite3"
    store = DurableIdempotencyStore(
        path,
        max_records=1,
        reservation_lease_s=10,
        retention_s=5,
        clock=lambda: now[0],
    )
    assert store.reserve(_scope()).acquired is True
    now[0] = 111
    stale = store.reserve(_scope())
    assert stale.result == BrokerResult("request-a", "failed", "unknown_outcome")
    now[0] = 117

    replacement = store.reserve(_scope(request_id="request-b"))
    assert replacement.acquired is True
    replay = DurableIdempotencyStore(path, retention_s=5, clock=lambda: now[0]).reserve(_scope())
    assert replay.acquired is True
