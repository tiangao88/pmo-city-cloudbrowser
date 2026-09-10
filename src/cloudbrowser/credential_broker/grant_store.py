"""Durable, principal-scoped credential grant storage."""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from .contracts import GrantAuthorization
from .service import ResolvedBinding

_MAX_TEXT_BYTES = 256
PRIOR_GRANT_TABLE = "grants"


def _text(value: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_TEXT_BYTES
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{label} is invalid")
    return value


class DurableGrantStore:
    """Resolve exact live grants from an atomic SQLite authorization table."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._initialize_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
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
                    CREATE TABLE IF NOT EXISTS grants (
                        profile_id TEXT NOT NULL,
                        principal_id TEXT NOT NULL,
                        site_id TEXT NOT NULL,
                        target_tab_id TEXT NOT NULL,
                        browser_id TEXT NOT NULL,
                        generation TEXT NOT NULL,
                        username_ref TEXT NOT NULL,
                        active INTEGER NOT NULL CHECK (active IN (0, 1)),
                        authorization_epoch INTEGER NOT NULL CHECK (authorization_epoch > 0),
                        PRIMARY KEY (profile_id, principal_id, site_id, target_tab_id)
                    )
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(grants)").fetchall()
                }
                if "authorization_epoch" not in columns:
                    connection.execute(
                        "ALTER TABLE grants ADD COLUMN authorization_epoch INTEGER NOT NULL DEFAULT 1"
                    )
            if self._path.exists():
                try:
                    os.chmod(self._path, 0o600)
                except OSError:
                    pass

    def put(
        self,
        *,
        profile_id: str,
        principal_id: str,
        site_id: str,
        target_tab_id: str,
        browser_id: str,
        generation: str,
        username_ref: str,
        active: bool = True,
    ) -> None:
        if not isinstance(active, bool):
            raise ValueError("active must be boolean")
        values = tuple(
            _text(value, label)
            for label, value in (
                ("profile_id", profile_id),
                ("principal_id", principal_id),
                ("site_id", site_id),
                ("target_tab_id", target_tab_id),
                ("browser_id", browser_id),
                ("generation", generation),
                ("username_ref", username_ref),
            )
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO grants (
                    profile_id, principal_id, site_id, target_tab_id,
                    browser_id, generation, username_ref, active, authorization_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, principal_id, site_id, target_tab_id)
                DO UPDATE SET
                    browser_id = excluded.browser_id,
                    generation = excluded.generation,
                    username_ref = excluded.username_ref,
                    active = excluded.active,
                    authorization_epoch = grants.authorization_epoch + 1
                """,
                (*values, int(active), 1),
            )
            connection.commit()

    def revoke(
        self,
        *,
        profile_id: str,
        principal_id: str,
        site_id: str,
        target_tab_id: str,
    ) -> bool:
        scope = tuple(
            _text(value, label)
            for label, value in (
                ("profile_id", profile_id),
                ("principal_id", principal_id),
                ("site_id", site_id),
                ("target_tab_id", target_tab_id),
            )
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE grants SET active = 0, authorization_epoch = authorization_epoch + 1
                WHERE profile_id = ? AND principal_id = ?
                  AND site_id = ? AND target_tab_id = ? AND active = 1
                """,
                scope,
            )
            connection.commit()
            return cursor.rowcount == 1

    def resolve(
        self,
        binding: ResolvedBinding,
        site_id: str,
        target_tab_id: str,
    ) -> GrantAuthorization:
        scope = tuple(
            _text(value, label)
            for label, value in (
                ("profile_id", binding.profile_id),
                ("principal_id", binding.principal_id),
                ("site_id", site_id),
                ("target_tab_id", target_tab_id),
            )
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT browser_id, generation, username_ref, active, authorization_epoch
                FROM grants
                WHERE profile_id = ? AND principal_id = ?
                  AND site_id = ? AND target_tab_id = ?
                """,
                scope,
            ).fetchone()
        if row is None:
            raise LookupError("grant unavailable")
        browser_id, generation, username_ref, active, authorization_epoch = row
        if active != 1:
            raise LookupError("grant revoked")
        if browser_id != binding.browser_id or generation != binding.generation:
            raise LookupError("grant unavailable")
        return GrantAuthorization(
            username_ref=username_ref,
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
            site_id=site_id,
            target_tab_id=target_tab_id,
            epoch=int(authorization_epoch),
        )


__all__ = ["DurableGrantStore", "PRIOR_GRANT_TABLE"]
