"""Durable, bounded, atomic replay protection for broker capabilities."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from .deadline import (
    BrokerDeadline,
    BrokerDeadlineExceeded,
    configure_sqlite_busy_timeout,
    sqlite_busy_timeout_s,
)

_MAX_TEXT_BYTES = 256
_DEFAULT_MAX_RECORDS = 100_000


class NonceStoreError(RuntimeError):
    """Replay state could not be safely updated."""


class NonceStoreFull(NonceStoreError):
    """The bounded store has no expired row available for pruning."""


class DurableNonceStore:
    """Consume ``(deployment, audience, nonce)`` once across threads/restarts.

    Each consume runs in an immediate SQLite transaction. Expired rows are
    pruned in that same transaction, while live rows are never evicted to make
    room. If the configured bound is reached, authorization fails closed.
    """

    def __init__(self, path: str | os.PathLike[str], *, max_records: int = _DEFAULT_MAX_RECORDS) -> None:
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self._path = Path(path)
        self._max_records = max_records
        self._initialize_lock = threading.Lock()
        self._initialize()

    def _connect(self, *, deadline: BrokerDeadline | None = None) -> sqlite3.Connection:
        timeout_s = sqlite_busy_timeout_s(deadline)
        connection = sqlite3.connect(
            self._path,
            timeout=timeout_s,
            isolation_level=None,
        )
        configure_sqlite_busy_timeout(connection, deadline)
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._initialize_lock:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.chmod(self._path.parent, 0o700)
            except OSError:
                pass
            try:
                connection = self._connect()
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS consumed_nonces (
                            deployment TEXT NOT NULL,
                            audience TEXT NOT NULL,
                            nonce TEXT NOT NULL,
                            expires_at INTEGER NOT NULL,
                            PRIMARY KEY (deployment, audience, nonce)
                        ) WITHOUT ROWID
                        """
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS consumed_nonces_expiry "
                        "ON consumed_nonces(expires_at)"
                    )
                finally:
                    connection.close()
                os.chmod(self._path, 0o600)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(f"{self._path}{suffix}")
                    if sidecar.exists():
                        os.chmod(sidecar, 0o600)
            except (OSError, sqlite3.Error) as exc:
                raise NonceStoreError("nonce store is unavailable") from exc

    def consume(
        self,
        *,
        deployment: str,
        audience: str,
        nonce: str,
        expires_at: int,
        now: int,
        deadline: BrokerDeadline | None = None,
    ) -> bool:
        for value, name in (
            (deployment, "deployment"),
            (audience, "audience"),
            (nonce, "nonce"),
        ):
            _validate_text(value, name)
        for value, name in ((expires_at, "expires_at"), (now, "now")):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer timestamp")
        if expires_at <= now:
            raise ValueError("cannot consume an expired nonce")

        connection: sqlite3.Connection | None = None
        try:
            if deadline is not None:
                deadline.check()
            connection = self._connect(deadline=deadline)
            connection.execute("BEGIN IMMEDIATE")
            if deadline is not None:
                deadline.check()
            connection.execute("DELETE FROM consumed_nonces WHERE expires_at <= ?", (now,))
            existing = connection.execute(
                "SELECT 1 FROM consumed_nonces "
                "WHERE deployment = ? AND audience = ? AND nonce = ?",
                (deployment, audience, nonce),
            ).fetchone()
            if existing is not None:
                connection.execute("ROLLBACK")
                return False
            count = connection.execute("SELECT COUNT(*) FROM consumed_nonces").fetchone()
            if count is None or int(count[0]) >= self._max_records:
                connection.execute("ROLLBACK")
                raise NonceStoreFull("nonce store capacity reached")
            connection.execute(
                "INSERT INTO consumed_nonces "
                "(deployment, audience, nonce, expires_at) VALUES (?, ?, ?, ?)",
                (deployment, audience, nonce, expires_at),
            )
            connection.execute("COMMIT")
            return True
        except BrokerDeadlineExceeded:
            raise
        except NonceStoreFull:
            raise
        except (OSError, sqlite3.Error) as exc:
            if deadline is not None and deadline.remaining() <= 0:
                raise BrokerDeadlineExceeded("broker deadline expired") from exc
            if connection is not None:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            raise NonceStoreError("nonce store is unavailable") from exc
        finally:
            if connection is not None:
                connection.close()


def _validate_text(value: object, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_TEXT_BYTES
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{name} is invalid")


__all__ = ["DurableNonceStore", "NonceStoreError", "NonceStoreFull"]
