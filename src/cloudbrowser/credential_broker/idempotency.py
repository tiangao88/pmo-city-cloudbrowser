"""In-memory compatibility and durable atomic broker idempotency stores."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Callable

from .contracts import BrokerResult
from .deadline import (
    BrokerDeadline,
    BrokerDeadlineExceeded,
    configure_sqlite_busy_timeout,
    sqlite_busy_timeout_s,
)

_MAX_TEXT_BYTES = 256
_DEFAULT_RESERVATION_LEASE_S = 60
_DEFAULT_RETENTION_S = 86_400
_DEFAULT_MAX_RECORDS = 100_000
_UNKNOWN_OUTCOME_ERROR = "unknown_outcome"


@dataclass
class IdempotencyStore:
    """Compatibility unit-test store; production uses ``DurableIdempotencyStore``."""

    _records: dict[tuple[str, str], BrokerResult] = field(default_factory=dict)

    def record(self, principal_id: str, idempotency_key: str, result: BrokerResult) -> None:
        key = (principal_id, idempotency_key)
        self._records.setdefault(key, result)

    def replay(self, principal_id: str, idempotency_key: str) -> BrokerResult | None:
        return self._records.get((principal_id, idempotency_key))


@dataclass(frozen=True)
class OperationScope:
    """Complete authorization/binding scope for one idempotent login."""

    deployment: str
    audience: str
    operation: str
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str
    site_id: str
    target_tab_id: str
    request_id: str

    def values(self) -> tuple[str, ...]:
        values: list[str] = []
        for descriptor in fields(self):
            value = getattr(self, descriptor.name)
            if (
                not isinstance(value, str)
                or not value
                or len(value.encode("utf-8")) > _MAX_TEXT_BYTES
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            ):
                raise ValueError(f"{descriptor.name} is invalid")
            values.append(value)
        return tuple(values)


@dataclass(frozen=True)
class Reservation:
    acquired: bool
    owner_token: str = ""
    result: BrokerResult | None = None


class IdempotencyStoreError(RuntimeError):
    """Durable idempotency state could not be safely updated."""


class IdempotencyStoreFull(IdempotencyStoreError):
    """No expired idempotency row is available for safe eviction."""


class DurableIdempotencyStore:
    """Atomically reserve and replay status-only results across restarts.

    A reservation is a lease, not permission to retry after a process crash. If
    its lease expires, the row is finalized as ``failed/unknown_outcome`` and
    remains replayable for the configured retention period. This deliberately
    prefers an indeterminate result over repeating a browser side effect that
    may already have happened.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        wait_timeout_s: float = 30.0,
        poll_interval_s: float = 0.01,
        reservation_lease_s: int = _DEFAULT_RESERVATION_LEASE_S,
        retention_s: int = _DEFAULT_RETENTION_S,
        max_records: int = _DEFAULT_MAX_RECORDS,
        clock: Callable[[], int] = lambda: int(time.time()),
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if wait_timeout_s <= 0 or poll_interval_s <= 0:
            raise ValueError("idempotency timeouts must be positive")
        if (
            isinstance(reservation_lease_s, bool)
            or not isinstance(reservation_lease_s, int)
            or reservation_lease_s <= 0
        ):
            raise ValueError("reservation_lease_s must be a positive integer")
        if isinstance(retention_s, bool) or not isinstance(retention_s, int) or retention_s <= 0:
            raise ValueError("retention_s must be a positive integer")
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        if not callable(clock):
            raise ValueError("clock must be callable")
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable")
        if not callable(sleep):
            raise ValueError("sleep must be callable")
        self._path = Path(path)
        self._wait_timeout_s = wait_timeout_s
        self._poll_interval_s = poll_interval_s
        self._reservation_lease_s = reservation_lease_s
        self._retention_s = retention_s
        self._max_records = max_records
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._sleep = sleep
        self._initialize_lock = threading.Lock()
        self._initialize()

    def _now(self) -> int:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, int):
            raise IdempotencyStoreError("idempotency clock is invalid")
        return value

    def _connect(self, *, deadline: BrokerDeadline | None = None) -> sqlite3.Connection:
        timeout_s = sqlite_busy_timeout_s(deadline)
        connection = sqlite3.connect(self._path, timeout=timeout_s, isolation_level=None)
        configure_sqlite_busy_timeout(connection, deadline)
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        now = self._now()
        with self._initialize_lock:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.chmod(self._path.parent, 0o700)
            except OSError:
                pass
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operations (
                        deployment TEXT NOT NULL,
                        audience TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        profile_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        browser_id TEXT NOT NULL,
                        generation TEXT NOT NULL,
                        site_id TEXT NOT NULL,
                        target_tab_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        owner_token TEXT NOT NULL,
                        state TEXT NOT NULL CHECK (state IN ('reserved', 'complete')),
                        status TEXT,
                        error_code TEXT,
                        duration_ms INTEGER,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        lease_expires_at INTEGER,
                        retained_until INTEGER,
                        PRIMARY KEY (
                            deployment, audience, operation, profile_id, principal_id,
                            browser_id, generation, site_id, target_tab_id, request_id
                        )
                    )
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(operations)").fetchall()
                }
                # Migrate databases created by the earlier durable store. The
                # defaults are only for SQLite's ALTER TABLE operation; the
                # update below gives old rows a safe lease/retention policy.
                for name, declaration in (
                    ("created_at", "INTEGER NOT NULL DEFAULT 0"),
                    ("updated_at", "INTEGER NOT NULL DEFAULT 0"),
                    ("lease_expires_at", "INTEGER"),
                    ("retained_until", "INTEGER"),
                ):
                    if name not in columns:
                        connection.execute(
                            f"ALTER TABLE operations ADD COLUMN {name} {declaration}"
                        )
                connection.execute(
                    """
                    UPDATE operations
                    SET created_at = CASE WHEN created_at = 0 THEN ? ELSE created_at END,
                        updated_at = CASE WHEN updated_at = 0 THEN ? ELSE updated_at END,
                        lease_expires_at = CASE
                            WHEN state = 'reserved' AND lease_expires_at IS NULL THEN ?
                            ELSE lease_expires_at
                        END,
                        retained_until = CASE
                            WHEN state = 'complete' AND retained_until IS NULL THEN ?
                            ELSE retained_until
                        END
                    WHERE created_at = 0
                       OR updated_at = 0
                       OR (state = 'reserved' AND lease_expires_at IS NULL)
                       OR (state = 'complete' AND retained_until IS NULL)
                    """,
                    (now, now, now, now + self._retention_s),
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS operations_retention "
                    "ON operations(state, retained_until)"
                )
            if self._path.exists():
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass

    @staticmethod
    def _unknown_result(scope: OperationScope) -> BrokerResult:
        return BrokerResult(scope.request_id, "failed", _UNKNOWN_OUTCOME_ERROR)

    @staticmethod
    def _row_result(scope: OperationScope, row: tuple[object, ...]) -> BrokerResult:
        state, status, error_code, duration_ms = row[:4]
        if state != "complete" or not isinstance(status, str):
            raise IdempotencyStoreError("idempotency row is not terminal")
        try:
            duration = 0 if duration_ms is None else int(duration_ms)
            if error_code is not None and not isinstance(error_code, str):
                raise ValueError("error_code is invalid")
            return BrokerResult(scope.request_id, status, error_code, duration)
        except (TypeError, ValueError) as exc:
            raise IdempotencyStoreError("idempotency row is invalid") from exc

    def reserve(
        self,
        scope: OperationScope,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> Reservation:
        if deadline is not None:
            deadline.check()
        key = scope.values()
        now = self._now()
        owner_token = uuid.uuid4().hex
        try:
            with self._connect(deadline=deadline) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if deadline is not None:
                    deadline.check()
                row = connection.execute(
                    """
                    SELECT state, status, error_code, duration_ms,
                           lease_expires_at, retained_until
                    FROM operations
                    WHERE deployment = ? AND audience = ? AND operation = ?
                      AND profile_id = ? AND principal_id = ? AND browser_id = ?
                      AND generation = ? AND site_id = ? AND target_tab_id = ?
                      AND request_id = ?
                    """,
                    key,
                ).fetchone()
                if row is not None:
                    state, _status, _error_code, _duration_ms, lease_expires_at, retained_until = row
                    if state == "reserved":
                        if isinstance(lease_expires_at, int) and lease_expires_at > now:
                            connection.commit()
                            return Reservation(False)
                        connection.execute(
                            """
                            UPDATE operations
                            SET state = 'complete', status = 'failed',
                                error_code = ?, duration_ms = 0,
                                updated_at = ?, lease_expires_at = NULL,
                                retained_until = ?
                            WHERE deployment = ? AND audience = ? AND operation = ?
                              AND profile_id = ? AND principal_id = ? AND browser_id = ?
                              AND generation = ? AND site_id = ? AND target_tab_id = ?
                              AND request_id = ? AND state = 'reserved'
                            """,
                            (_UNKNOWN_OUTCOME_ERROR, now, now + self._retention_s, *key),
                        )
                        connection.commit()
                        return Reservation(False, result=self._unknown_result(scope))
                    if not isinstance(retained_until, int) or retained_until > now:
                        connection.commit()
                        return Reservation(False, result=self._row_result(scope, row))
                    connection.execute(
                        """
                        DELETE FROM operations
                        WHERE deployment = ? AND audience = ? AND operation = ?
                          AND profile_id = ? AND principal_id = ? AND browser_id = ?
                          AND generation = ? AND site_id = ? AND target_tab_id = ?
                          AND request_id = ?
                        """,
                        key,
                    )

                connection.execute(
                    """
                    UPDATE operations
                    SET state = 'complete', status = 'failed',
                        error_code = ?, duration_ms = 0,
                        updated_at = ?, lease_expires_at = NULL,
                        retained_until = ?
                    WHERE state = 'reserved' AND lease_expires_at <= ?
                    """,
                    (_UNKNOWN_OUTCOME_ERROR, now, now + self._retention_s, now),
                )
                connection.execute(
                    """
                    DELETE FROM operations
                    WHERE state = 'complete' AND retained_until <= ?
                    """,
                    (now,),
                )
                count_row = connection.execute("SELECT COUNT(*) FROM operations").fetchone()
                if count_row is None or int(count_row[0]) >= self._max_records:
                    connection.commit()
                    raise IdempotencyStoreFull("idempotency store capacity reached")
                connection.execute(
                    """
                    INSERT INTO operations (
                        deployment, audience, operation, profile_id, principal_id,
                        browser_id, generation, site_id, target_tab_id, request_id,
                        owner_token, state, created_at, updated_at, lease_expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?)
                    """,
                    (*key, owner_token, now, now, now + self._reservation_lease_s),
                )
                connection.commit()
                return Reservation(True, owner_token)
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            if deadline is not None and deadline.remaining() <= 0:
                raise BrokerDeadlineExceeded("broker deadline expired") from exc
            raise IdempotencyStoreError("idempotency store is unavailable") from exc

    def complete(
        self,
        scope: OperationScope,
        owner_token: str,
        result: BrokerResult,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        if deadline is not None:
            deadline.check()
        if result.request_id != scope.request_id:
            raise ValueError("idempotency result request_id does not match scope")
        key = scope.values()
        now = self._now()
        try:
            with self._connect(deadline=deadline) as connection:
                connection.execute("BEGIN IMMEDIATE")
                if deadline is not None:
                    deadline.check()
                cursor = connection.execute(
                    """
                    UPDATE operations
                    SET state = 'complete', status = ?, error_code = ?, duration_ms = ?,
                        updated_at = ?, lease_expires_at = NULL, retained_until = ?
                    WHERE deployment = ? AND audience = ? AND operation = ?
                      AND profile_id = ? AND principal_id = ? AND browser_id = ?
                      AND generation = ? AND site_id = ? AND target_tab_id = ?
                      AND request_id = ? AND owner_token = ? AND state = 'reserved'
                    """,
                    (
                        result.status,
                        result.error_code,
                        result.duration_ms,
                        now,
                        now + self._retention_s,
                        *key,
                        owner_token,
                    ),
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise IdempotencyStoreError("idempotency reservation is not owned")
                connection.commit()
        except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            if deadline is not None and deadline.remaining() <= 0:
                raise BrokerDeadlineExceeded("broker deadline expired") from exc
            raise IdempotencyStoreError("idempotency store is unavailable") from exc

    def release(self, scope: OperationScope, owner_token: str) -> None:
        """Finalize a reservation as unknown; never make it silently retryable."""
        self._mark_unknown(scope, owner_token)

    def _mark_unknown(self, scope: OperationScope, owner_token: str) -> None:
        key = scope.values()
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE operations
                SET state = 'complete', status = 'failed',
                    error_code = ?, duration_ms = 0,
                    updated_at = ?, lease_expires_at = NULL,
                    retained_until = ?
                WHERE deployment = ? AND audience = ? AND operation = ?
                  AND profile_id = ? AND principal_id = ? AND browser_id = ?
                  AND generation = ? AND site_id = ? AND target_tab_id = ?
                  AND request_id = ? AND owner_token = ? AND state = 'reserved'
                """,
                (_UNKNOWN_OUTCOME_ERROR, now, now + self._retention_s, *key, owner_token),
            )
            connection.commit()

    def execute(
        self,
        scope: OperationScope,
        operation: Callable[[], BrokerResult],
        *,
        deadline: BrokerDeadline | None = None,
    ) -> BrokerResult:
        wait_deadline = self._monotonic_clock() + self._wait_timeout_s
        while True:
            if deadline is not None:
                deadline.check()
            if self._monotonic_clock() >= wait_deadline:
                raise IdempotencyStoreError("idempotent operation remains in progress")
            reservation = self.reserve(scope, deadline=deadline)
            if reservation.result is not None:
                return reservation.result
            if reservation.acquired:
                try:
                    if deadline is not None:
                        deadline.check()
                    result = operation()
                    self.complete(
                        scope,
                        reservation.owner_token,
                        result,
                        deadline=deadline,
                    )
                    return result
                except BaseException:
                    # The operation may have reached the external side effect
                    # before raising. Do not release the key for a blind retry.
                    try:
                        self._mark_unknown(scope, reservation.owner_token)
                    except BaseException:
                        # The lease still provides a bounded convergence path if
                        # the crash happens while recording this terminal state.
                        pass
                    raise
            if deadline is not None:
                remaining = min(deadline.check(), wait_deadline - self._monotonic_clock())
            else:
                remaining = wait_deadline - self._monotonic_clock()
            if remaining <= 0:
                if deadline is not None and deadline.remaining() <= 0:
                    deadline.check()
                raise IdempotencyStoreError("idempotent operation remains in progress")
            self._sleep(min(self._poll_interval_s, remaining))


__all__ = [
    "DurableIdempotencyStore",
    "IdempotencyStore",
    "IdempotencyStoreError",
    "IdempotencyStoreFull",
    "OperationScope",
    "Reservation",
]
