"""Production GrantHub two-leg custody and broker-only consumption.

The store is deliberately separate from the historical ``DurableGrantStore``:
that table only authorized an item reference and had no custody or operator
lifecycle.  This module owns the complete production contract:

* an immutable binding is the grant key; caller email is never a lookup key;
* each grant has a random per-grant wrapping key (``K_user``);
* the vault key and refresh-token/session leg are independently AES-GCM wrapped
  under ``K_user``;
* ``K_user`` is AES-GCM wrapped by a broker key-encryption key supplied at
  process/CLI start, never stored in the database;
* provisioning and revocation update custody, authorization epoch, and the
  redacted audit record in one SQLite transaction;
* the broker resolves an opaque grant reference and unwraps material only in a
  one-call context; refresh rotation is persisted only while the same active
  epoch remains valid.

The KEK is intentionally not generated or persisted here.  Operators provide
it through a platform secret at broker startup and through an explicit offline
admin input for provisioning.  An installation without that key fails closed.
No master password, plaintext vault key, access token, or refresh token is
stored by this module.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, TypeVar

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.security import vault_crypto as crypto

from .contracts import AuthorizationChanged, GrantAuthorization
from .deadline import (
    BrokerDeadline,
    BrokerDeadlineExceeded,
    configure_sqlite_busy_timeout,
    invoke_transport,
    invoke_with_deadline,
    sqlite_busy_timeout_s,
)
from .service import DependencyUnavailable, ResolvedBinding

_MAX_TEXT_BYTES = 256
_MAX_ITEM_REF_BYTES = 512
_MAX_REFRESH_TOKEN_BYTES = 16 * 1024
_GRANT_REF_PREFIX = "grantref:v1."
_SCHEMA_VERSION = 1
_SCHEMA_ID = "cloudbrowser.grant-custody.v1"
_CONSENT_BINDING = "@consent:v1"

Transport = Callable[..., tuple[int, bytes]]
_Result = TypeVar("_Result")


class _ScopeLocks:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[tuple[str, ...], threading.RLock] = {}

    def lock_for(self, key: tuple[str, ...]) -> threading.RLock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._locks[key] = lock
            return lock


_GLOBAL_SCOPE_LOCKS = _ScopeLocks()


class GrantCustodyError(RuntimeError):
    """Base error for grant custody failures."""


class GrantRevoked(LookupError, GrantCustodyError):
    """The grant was revoked or its authorization epoch changed."""


class GrantMaterialError(GrantCustodyError):
    """Wrapped material was malformed or failed authenticated decryption."""


@dataclass(frozen=True)
class GrantScope:
    """The complete immutable owner/browser/site key for one grant."""

    profile_id: str
    principal_id: str
    site_id: str
    target_tab_id: str
    browser_id: str
    generation: str

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "principal_id",
            "site_id",
            "target_tab_id",
            "browser_id",
            "generation",
        ):
            _bounded_text(getattr(self, name), name)
        ephemeral = (self.target_tab_id, self.browser_id, self.generation)
        if _CONSENT_BINDING in ephemeral and ephemeral != (_CONSENT_BINDING,) * 3:
            raise ValueError("partial consent scope is invalid")

    @classmethod
    def consent(cls, *, profile_id: str, principal_id: str, site_id: str) -> "GrantScope":
        """Explicit durable approval, not an ephemeral browser capability.

        The versioned reserved tuple uses the existing authenticated envelope
        schema. Old exact grants are never inferred into this scope.
        """
        return cls(profile_id, principal_id, site_id, _CONSENT_BINDING, _CONSENT_BINDING, _CONSENT_BINDING)

    @property
    def is_consent(self) -> bool:
        return (self.target_tab_id, self.browser_id, self.generation) == (_CONSENT_BINDING,) * 3

    def permits_request_scope(self, request: "GrantScope") -> bool:
        if request.is_consent:
            return False
        return self == request or (
            self.is_consent
            and (self.profile_id, self.principal_id, self.site_id) == (request.profile_id, request.principal_id, request.site_id)
        )

    @classmethod
    def from_binding(
        cls,
        binding: ResolvedBinding,
        *,
        site_id: str,
        target_tab_id: str,
    ) -> "GrantScope":
        return cls(
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            site_id=site_id,
            target_tab_id=target_tab_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
        )

    def canonical(self) -> bytes:
        """Return a stable, non-secret AAD representation of the scope."""
        return json.dumps(
            {
                "browser_id": self.browser_id,
                "generation": self.generation,
                "principal_id": self.principal_id,
                "profile_id": self.profile_id,
                "site_id": self.site_id,
                "target_tab_id": self.target_tab_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True)
class ProvisionedGrant:
    """Opaque operator result; it contains no grant material."""

    grant_ref: str
    epoch: int


@dataclass(frozen=True)
class _Envelope:
    nonce: bytes
    ciphertext: bytes
    tag: bytes


@dataclass
class GrantLease:
    """One-call plaintext view; references are wiped on context exit."""

    _store: "CustodyGrantStore"
    _grant_id: str
    _epoch: int
    _scope: GrantScope
    _item_ref: str
    _k_user: bytearray
    _vault_key: bytearray
    _refresh_token: bytearray
    _write_connection: sqlite3.Connection | None = None
    _owns_write_transaction: bool = False
    _rotated_refresh_token: bytearray | None = None
    _closed: bool = False

    @property
    def scope(self) -> GrantScope:
        self._ensure_open()
        return self._scope

    @property
    def item_ref(self) -> str:
        self._ensure_open()
        return self._item_ref

    @property
    def vault_key(self) -> bytes:
        self._ensure_open()
        return bytes(self._vault_key)

    @property
    def refresh_token(self) -> bytes:
        self._ensure_open()
        return bytes(self._refresh_token)

    @property
    def epoch(self) -> int:
        self._ensure_open()
        return self._epoch

    def recheck(self) -> None:
        """Fail closed if revocation or reassignment won a race."""
        self._ensure_open()
        self._store._recheck(self._grant_id, self._scope, self._epoch)

    def rotate_refresh_token(self, refresh_token: bytes) -> None:
        """Persist a rotated session leg only in the same live epoch."""
        self._ensure_open()
        _validate_refresh_token(refresh_token)
        self._store._rotate_refresh_token(
            self._grant_id,
            self._scope,
            self._epoch,
            bytes(self._k_user),
            refresh_token,
            connection=self._write_connection,
        )
        self._wipe(self._refresh_token)
        self._refresh_token = bytearray(refresh_token)

    def commit_invalidation(self) -> None:
        """Commit an invalidation that must survive the raised rejection."""
        if self._write_connection is not None and self._owns_write_transaction:
            self._write_connection.commit()
            self._owns_write_transaction = False

    def invalidate(self) -> None:
        """Invalidate this grant after a definitive refresh rejection."""
        self._ensure_open()
        self._store._invalidate(
            self._grant_id,
            self._scope,
            self._epoch,
            connection=self._write_connection,
        )
        self._closed = True
        self._wipe_all()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._wipe_all()

    def __enter__(self) -> "GrantLease":
        self._ensure_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise GrantMaterialError("grant lease is closed")

    @staticmethod
    def _wipe(value: bytearray) -> None:
        value[:] = b"\x00" * len(value)

    def _wipe_all(self) -> None:
        self._wipe(self._k_user)
        self._wipe(self._vault_key)
        self._wipe(self._refresh_token)
        if self._rotated_refresh_token is not None:
            self._wipe(self._rotated_refresh_token)
        self._item_ref = ""


class CustodyGrantStore:
    """Owner-only SQLite store for per-principal two-leg grant custody."""

    def __init__(self, path: str | os.PathLike[str], *, kek: bytes) -> None:
        self._path = Path(path)
        self._kek = _validate_kek(kek)
        self._initialize_lock = threading.Lock()
        self._initialize()

    def _connect(self, *, deadline: BrokerDeadline | None = None) -> sqlite3.Connection:
        timeout_s = sqlite_busy_timeout_s(deadline)
        connection = sqlite3.connect(self._path, timeout=timeout_s, isolation_level=None)
        configure_sqlite_busy_timeout(connection, deadline)
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._initialize_lock:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _chmod_best_effort(self._path.parent, 0o700)
            schema = _inspect_database_schema(self._path)
            if schema is not None and schema["tables"]:
                _validate_custody_schema(schema)
            else:
                with self._connect() as connection:
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        connection.execute(
                            """
                            CREATE TABLE grant_custody (
                                grant_id TEXT PRIMARY KEY,
                                profile_id TEXT NOT NULL,
                                principal_id TEXT NOT NULL,
                                site_id TEXT NOT NULL,
                                target_tab_id TEXT NOT NULL,
                                browser_id TEXT NOT NULL,
                                generation TEXT NOT NULL,
                                epoch INTEGER NOT NULL CHECK (epoch >= 1),
                                active INTEGER NOT NULL CHECK (active IN (0, 1)),
                                wrapped_k_user_nonce BLOB,
                                wrapped_k_user_ct BLOB,
                                wrapped_k_user_tag BLOB,
                                wrapped_vault_key_nonce BLOB,
                                wrapped_vault_key_ct BLOB,
                                wrapped_vault_key_tag BLOB,
                                wrapped_session_nonce BLOB,
                                wrapped_session_ct BLOB,
                                wrapped_session_tag BLOB,
                                wrapped_item_ref_nonce BLOB,
                                wrapped_item_ref_ct BLOB,
                                wrapped_item_ref_tag BLOB,
                                created_at INTEGER NOT NULL,
                                updated_at INTEGER NOT NULL,
                                UNIQUE(profile_id, principal_id, site_id, target_tab_id,
                                       browser_id, generation)
                            )
                            """
                        )
                        connection.execute(
                            """
                            CREATE TABLE grant_audit (
                                event_id TEXT PRIMARY KEY,
                                event TEXT NOT NULL,
                                operator_id TEXT NOT NULL,
                                grant_id TEXT NOT NULL,
                                epoch INTEGER NOT NULL,
                                outcome TEXT NOT NULL,
                                created_at INTEGER NOT NULL
                            )
                            """
                        )
                        connection.execute(
                            """
                            CREATE TABLE grant_metadata (
                                schema_id TEXT NOT NULL,
                                schema_version INTEGER NOT NULL
                            )
                            """
                        )
                        connection.execute(
                            """
                            INSERT INTO grant_metadata(schema_id, schema_version)
                            VALUES (?, ?)
                            """,
                            (_SCHEMA_ID, _SCHEMA_VERSION),
                        )
                    except Exception:
                        connection.rollback()
                        raise
                    connection.commit()
            self._lockdown_files()

    def _lock_for_scope(self, scope: GrantScope) -> threading.RLock:
        """Return the process-wide lock shared by broker/admin store instances."""
        return _GLOBAL_SCOPE_LOCKS.lock_for(_scope_values(scope))

    def _lock_for_grant(self, grant_id: str) -> threading.RLock:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT profile_id, principal_id, site_id, target_tab_id, browser_id, generation "
                "FROM grant_custody WHERE grant_id = ?",
                (grant_id,),
            ).fetchone()
        if row is None:
            raise GrantRevoked("grant revoked")
        return self._lock_for_scope(
            GrantScope(
                profile_id=str(row[0]),
                principal_id=str(row[1]),
                site_id=str(row[2]),
                target_tab_id=str(row[3]),
                browser_id=str(row[4]),
                generation=str(row[5]),
            )
        )

    @contextmanager
    def authorized_operation(
        self,
        grant_ref: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> Iterator[GrantLease]:
        """Hold the grant write gate through one browser side effect."""
        grant_id = _parse_grant_ref(grant_ref)
        lock = self._lock_for_grant(grant_id)
        if deadline is None:
            lock.acquire()
        else:
            acquired = lock.acquire(timeout=deadline.check())
            if not acquired:
                raise BrokerDeadlineExceeded("broker deadline expired")
            deadline.check()
        try:
            connection = self._connect(deadline=deadline)
            lease: GrantLease | None = None
            try:
                # This write reservation coordinates every custody mutator that
                # uses this database, including a separate operator process.
                connection.execute("BEGIN IMMEDIATE")
                lease = self._checkout(grant_ref)
                lease._write_connection = connection
                lease._owns_write_transaction = True
                yield lease
                connection.commit()
            except BaseException:
                if lease is None or lease._owns_write_transaction:
                    connection.rollback()
                raise
            finally:
                if lease is not None:
                    lease._owns_write_transaction = False
                    lease.close()
                connection.close()
        except sqlite3.OperationalError as exc:
            if deadline is not None and deadline.remaining() <= 0:
                raise BrokerDeadlineExceeded("broker deadline expired") from exc
            raise GrantCustodyError("grant custody store is unavailable") from exc
        finally:
            lock.release()


    def close(self) -> None:
        """Compatibility no-op; connections are short-lived per transaction."""

    def provision(
        self,
        *,
        scope: GrantScope,
        item_ref: str,
        vault_key: bytes,
        refresh_token: bytes,
        operator_id: str,
    ) -> ProvisionedGrant:
        _validate_item_ref(item_ref)
        _validate_vault_key(vault_key)
        _validate_refresh_token(refresh_token)
        with self._lock_for_scope(scope):
            return self._provision_unlocked(
                scope=scope,
                item_ref=item_ref,
                vault_key=vault_key,
                refresh_token=refresh_token,
                operator_id=operator_id,
            )

    def _provision_unlocked(
        self,
        *,
        scope: GrantScope,
        item_ref: str,
        vault_key: bytes,
        refresh_token: bytes,
        operator_id: str,
    ) -> ProvisionedGrant:
        _validate_item_ref(item_ref)
        _validate_vault_key(vault_key)
        _validate_refresh_token(refresh_token)
        operator = _bounded_text(operator_id, "operator_id")
        grant_id = secrets.token_urlsafe(24)
        now = int(time.time())
        k_user = secrets.token_bytes(32)
        wrapped = self._wrapped_legs(
            grant_id=grant_id,
            scope=scope,
            k_user=k_user,
            vault_key=vault_key,
            refresh_token=refresh_token,
            item_ref=item_ref,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Consent is explicitly chosen and cannot coexist with an active
            # older exact grant for this owner/site. Withdrawal therefore has
            # no second active authorization path hidden behind it.
            active_scopes = connection.execute(
                "SELECT target_tab_id, browser_id, generation FROM grant_custody "
                "WHERE profile_id = ? AND principal_id = ? AND site_id = ? AND active = 1",
                (scope.profile_id, scope.principal_id, scope.site_id),
            ).fetchall()
            if any((tuple(row) == (_CONSENT_BINDING,) * 3) != scope.is_consent for row in active_scopes):
                connection.rollback()
                raise ValueError("revoke prior grant scope before changing consent mode")
            old = connection.execute(
                """
                SELECT grant_id, epoch
                FROM grant_custody
                WHERE profile_id = ? AND principal_id = ? AND site_id = ?
                  AND target_tab_id = ? AND browser_id = ? AND generation = ?
                """,
                _scope_values(scope),
            ).fetchone()
            epoch = int(old[1]) + 1 if old else 1
            if old:
                connection.execute(
                    """
                    UPDATE grant_custody SET
                        grant_id = ?, epoch = ?, active = 1,
                        wrapped_k_user_nonce = ?, wrapped_k_user_ct = ?, wrapped_k_user_tag = ?,
                        wrapped_vault_key_nonce = ?, wrapped_vault_key_ct = ?, wrapped_vault_key_tag = ?,
                        wrapped_session_nonce = ?, wrapped_session_ct = ?, wrapped_session_tag = ?,
                        wrapped_item_ref_nonce = ?, wrapped_item_ref_ct = ?, wrapped_item_ref_tag = ?,
                        updated_at = ?
                    WHERE profile_id = ? AND principal_id = ? AND site_id = ?
                      AND target_tab_id = ? AND browser_id = ? AND generation = ?
                    """,
                    (
                        grant_id,
                        epoch,
                        *wrapped["k_user"],
                        *wrapped["vault_key"],
                        *wrapped["session"],
                        *wrapped["item_ref"],
                        now,
                        *_scope_values(scope),
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO grant_custody (
                        grant_id, profile_id, principal_id, site_id, target_tab_id,
                        browser_id, generation, epoch, active,
                        wrapped_k_user_nonce, wrapped_k_user_ct, wrapped_k_user_tag,
                        wrapped_vault_key_nonce, wrapped_vault_key_ct, wrapped_vault_key_tag,
                        wrapped_session_nonce, wrapped_session_ct, wrapped_session_tag,
                        wrapped_item_ref_nonce, wrapped_item_ref_ct, wrapped_item_ref_tag,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        grant_id,
                        *_scope_values(scope),
                        epoch,
                        *wrapped["k_user"],
                        *wrapped["vault_key"],
                        *wrapped["session"],
                        *wrapped["item_ref"],
                        now,
                        now,
                    ),
                )
            self._audit_insert(
                connection,
                event="grant_provisioned",
                operator_id=operator,
                grant_id=grant_id,
                epoch=epoch,
                outcome="usable",
                created_at=now,
            )
            connection.commit()
        self._lockdown_files()
        return ProvisionedGrant(_grant_ref(grant_id), epoch)

    def revoke(self, *, scope: GrantScope, operator_id: str) -> bool:
        with self._lock_for_scope(scope):
            return self._revoke_unlocked(scope=scope, operator_id=operator_id)

    def _revoke_unlocked(self, *, scope: GrantScope, operator_id: str) -> bool:
        operator = _bounded_text(operator_id, "operator_id")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT grant_id, epoch, active
                FROM grant_custody
                WHERE profile_id = ? AND principal_id = ? AND site_id = ?
                  AND target_tab_id = ? AND browser_id = ? AND generation = ?
                """,
                _scope_values(scope),
            ).fetchone()
            if row is None:
                connection.commit()
                return False
            grant_id, old_epoch, active = str(row[0]), int(row[1]), int(row[2])
            if active == 1:
                new_epoch = old_epoch + 1
                connection.execute(
                    """
                    UPDATE grant_custody SET
                        epoch = ?, active = 0,
                        wrapped_k_user_nonce = NULL, wrapped_k_user_ct = NULL, wrapped_k_user_tag = NULL,
                        wrapped_vault_key_nonce = NULL, wrapped_vault_key_ct = NULL, wrapped_vault_key_tag = NULL,
                        wrapped_session_nonce = NULL, wrapped_session_ct = NULL, wrapped_session_tag = NULL,
                        wrapped_item_ref_nonce = NULL, wrapped_item_ref_ct = NULL, wrapped_item_ref_tag = NULL,
                        updated_at = ?
                    WHERE grant_id = ? AND epoch = ? AND active = 1
                    """,
                    (new_epoch, now, grant_id, old_epoch),
                )
                outcome = "revoked"
                audit_epoch = new_epoch
            else:
                outcome = "already_revoked"
                audit_epoch = old_epoch
            self._audit_insert(
                connection,
                event="grant_revoked",
                operator_id=operator,
                grant_id=grant_id,
                epoch=audit_epoch,
                outcome=outcome,
                created_at=now,
            )
            connection.commit()
        self._lockdown_files()
        return active == 1

    def status(self, scope: GrantScope, *, operator_id: str) -> dict[str, object]:
        operator = _bounded_text(operator_id, "operator_id")
        now = int(time.time())
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT active, epoch,
                       wrapped_vault_key_ct, wrapped_session_ct,
                       grant_id
                FROM grant_custody
                WHERE profile_id = ? AND principal_id = ? AND site_id = ?
                  AND target_tab_id = ? AND browser_id = ? AND generation = ?
                """,
                _scope_values(scope),
            ).fetchone()
            if row is None:
                active, epoch, vault_ct, session_ct, grant_id = 0, 0, None, None, "none"
            else:
                active, epoch, vault_ct, session_ct, grant_id = (
                    int(row[0]), int(row[1]), row[2], row[3], str(row[4])
                )
            self._audit_insert(
                connection,
                event="grant_status_read",
                operator_id=operator,
                grant_id=grant_id,
                epoch=epoch,
                outcome="active" if active else "inactive",
                created_at=now,
            )
            connection.commit()
        return {
            **_scope_dict(scope),
            "active": bool(active),
            "epoch": epoch,
            "has_vault_key": bool(active and vault_ct is not None),
            "has_session_leg": bool(active and session_ct is not None),
            "usable": bool(active and vault_ct is not None and session_ct is not None),
        }

    def audit(self, *, operator_id: str) -> list[dict[str, object]]:
        _bounded_text(operator_id, "operator_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event, operator_id, grant_id, epoch, outcome, created_at
                FROM grant_audit ORDER BY created_at ASC, event_id ASC
                """
            ).fetchall()
        return [
            {
                "event_id": str(row[0]),
                "event": str(row[1]),
                "operator_id": str(row[2]),
                "grant_id": str(row[3]),
                "epoch": int(row[4]),
                "outcome": str(row[5]),
                "created_at": int(row[6]),
            }
            for row in rows
        ]

    def resolve(
        self,
        binding: ResolvedBinding,
        site_id: str,
        target_tab_id: str,
    ) -> GrantAuthorization:
        scope = GrantScope.from_binding(binding, site_id=site_id, target_tab_id=target_tab_id)
        if scope.is_consent:
            raise LookupError("request must name an exact browser target")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT grant_id, active, browser_id, generation, epoch
                FROM grant_custody
                WHERE profile_id = ? AND principal_id = ? AND site_id = ?
                  AND target_tab_id = ? AND browser_id = ? AND generation = ?
                """,
                _scope_values(scope),
            ).fetchone()
            if row is None or int(row[1]) != 1:
                consent = GrantScope.consent(profile_id=scope.profile_id, principal_id=scope.principal_id, site_id=scope.site_id)
                row = connection.execute(
                    "SELECT grant_id, active, browser_id, generation, epoch FROM grant_custody "
                    "WHERE profile_id = ? AND principal_id = ? AND site_id = ? "
                    "AND target_tab_id = ? AND browser_id = ? AND generation = ?",
                    _scope_values(consent),
                ).fetchone()
        if row is None:
            raise LookupError("grant unavailable")
        if int(row[1]) != 1:
            raise LookupError("grant revoked")
        if (str(row[2]), str(row[3])) != (_CONSENT_BINDING,) * 2 and (str(row[2]) != binding.browser_id or str(row[3]) != binding.generation):
            raise LookupError("grant unavailable")
        return GrantAuthorization(
            username_ref=_grant_ref(str(row[0])),
            profile_id=scope.profile_id,
            principal_id=scope.principal_id,
            browser_id=scope.browser_id,
            generation=scope.generation,
            site_id=scope.site_id,
            target_tab_id=scope.target_tab_id,
            epoch=int(row[4]),
        )

    @contextmanager
    def checkout(self, grant_ref: str) -> Iterator[GrantLease]:
        lease = self._checkout(grant_ref)
        try:
            yield lease
        finally:
            lease.close()

    def _checkout(self, grant_ref: str) -> GrantLease:
        grant_id = _parse_grant_ref(grant_ref)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT profile_id, principal_id, site_id, target_tab_id,
                       browser_id, generation, epoch, active,
                       wrapped_k_user_nonce, wrapped_k_user_ct, wrapped_k_user_tag,
                       wrapped_vault_key_nonce, wrapped_vault_key_ct, wrapped_vault_key_tag,
                       wrapped_session_nonce, wrapped_session_ct, wrapped_session_tag,
                       wrapped_item_ref_nonce, wrapped_item_ref_ct, wrapped_item_ref_tag
                FROM grant_custody WHERE grant_id = ?
                """,
                (grant_id,),
            ).fetchone()
        if row is None:
            raise GrantRevoked("grant revoked")
        scope = GrantScope(
            profile_id=str(row[0]),
            principal_id=str(row[1]),
            site_id=str(row[2]),
            target_tab_id=str(row[3]),
            browser_id=str(row[4]),
            generation=str(row[5]),
        )
        epoch, active = int(row[6]), int(row[7])
        if active != 1:
            raise GrantRevoked("grant revoked")
        try:
            k_user = _unwrap(
                self._kek,
                _envelope(row[8:11]),
                _aad(grant_id, scope, "k_user"),
            )
            vault_key = _unwrap(
                k_user,
                _envelope(row[11:14]),
                _aad(grant_id, scope, "vault_key"),
            )
            refresh_token = _unwrap(
                k_user,
                _envelope(row[14:17]),
                _aad(grant_id, scope, "session"),
            )
            item_ref = _unwrap(
                k_user,
                _envelope(row[17:20]),
                _aad(grant_id, scope, "item_ref"),
            ).decode("utf-8")
        except (crypto.VaultCryptoError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise GrantMaterialError("grant material is unavailable") from exc
        _validate_vault_key(vault_key)
        _validate_refresh_token(refresh_token)
        _validate_item_ref(item_ref)
        return GrantLease(
            self,
            grant_id,
            epoch,
            scope,
            item_ref,
            bytearray(k_user),
            bytearray(vault_key),
            bytearray(refresh_token),
        )

    def _recheck(self, grant_id: str, scope: GrantScope, epoch: int) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT active, epoch,
                       profile_id, principal_id, site_id, target_tab_id,
                       browser_id, generation
                FROM grant_custody WHERE grant_id = ?
                """,
                (grant_id,),
            ).fetchone()
        if row is None or int(row[0]) != 1 or int(row[1]) != epoch:
            raise GrantRevoked("grant revoked")
        observed = GrantScope(
            profile_id=str(row[2]),
            principal_id=str(row[3]),
            site_id=str(row[4]),
            target_tab_id=str(row[5]),
            browser_id=str(row[6]),
            generation=str(row[7]),
        )
        if observed != scope:
            raise GrantRevoked("grant revoked")

    def _rotate_refresh_token(
        self,
        grant_id: str,
        scope: GrantScope,
        epoch: int,
        k_user: bytes,
        refresh_token: bytes,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        wrapped = _wrap(refresh_token, k_user, _aad(grant_id, scope, "session"))
        now = int(time.time())
        if connection is not None:
            self._rotate_refresh_token_on_connection(
                connection,
                grant_id,
                scope,
                epoch,
                wrapped,
                now,
            )
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._rotate_refresh_token_on_connection(
                connection,
                grant_id,
                scope,
                epoch,
                wrapped,
                now,
            )
            connection.commit()

    def _rotate_refresh_token_on_connection(
        self,
        connection: sqlite3.Connection,
        grant_id: str,
        scope: GrantScope,
        epoch: int,
        wrapped: tuple[bytes, bytes, bytes],
        now: int,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE grant_custody SET
                wrapped_session_nonce = ?, wrapped_session_ct = ?, wrapped_session_tag = ?,
                updated_at = ?
            WHERE grant_id = ? AND profile_id = ? AND principal_id = ? AND site_id = ?
              AND target_tab_id = ? AND browser_id = ? AND generation = ?
              AND epoch = ? AND active = 1
            """,
            (
                *wrapped,
                now,
                grant_id,
                *_scope_values(scope),
                epoch,
            ),
        )
        if cursor.rowcount != 1:
            raise GrantRevoked("grant revoked")
        self._audit_insert(
            connection,
            event="grant_session_rotated",
            operator_id="broker",
            grant_id=grant_id,
            epoch=epoch,
            outcome="stored",
            created_at=now,
        )
        self._lockdown_files()

    def _invalidate(
        self,
        grant_id: str,
        scope: GrantScope,
        epoch: int,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        now = int(time.time())
        owns_connection = connection is None
        connection = connection or self._connect()
        try:
            if owns_connection:
                connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE grant_custody SET
                    epoch = ?, active = 0,
                    wrapped_k_user_nonce = NULL, wrapped_k_user_ct = NULL, wrapped_k_user_tag = NULL,
                    wrapped_vault_key_nonce = NULL, wrapped_vault_key_ct = NULL, wrapped_vault_key_tag = NULL,
                    wrapped_session_nonce = NULL, wrapped_session_ct = NULL, wrapped_session_tag = NULL,
                    wrapped_item_ref_nonce = NULL, wrapped_item_ref_ct = NULL, wrapped_item_ref_tag = NULL,
                    updated_at = ?
                WHERE grant_id = ? AND profile_id = ? AND principal_id = ? AND site_id = ?
                  AND target_tab_id = ? AND browser_id = ? AND generation = ?
                  AND epoch = ? AND active = 1
                """,
                (epoch + 1, now, grant_id, *_scope_values(scope), epoch),
            )
            if cursor.rowcount == 1:
                self._audit_insert(
                    connection,
                    event="grant_invalidated",
                    operator_id="broker",
                    grant_id=grant_id,
                    epoch=epoch + 1,
                    outcome="refresh_rejected",
                    created_at=now,
                )
            if owns_connection:
                connection.commit()
        finally:
            if owns_connection:
                connection.close()
        self._lockdown_files()

    def _wrapped_legs(
        self,
        *,
        grant_id: str,
        scope: GrantScope,
        k_user: bytes,
        vault_key: bytes,
        refresh_token: bytes,
        item_ref: str,
    ) -> dict[str, tuple[bytes, bytes, bytes]]:
        return {
            "k_user": _wrap(k_user, self._kek, _aad(grant_id, scope, "k_user")),
            "vault_key": _wrap(vault_key, k_user, _aad(grant_id, scope, "vault_key")),
            "session": _wrap(refresh_token, k_user, _aad(grant_id, scope, "session")),
            "item_ref": _wrap(item_ref.encode("utf-8"), k_user, _aad(grant_id, scope, "item_ref")),
        }

    @staticmethod
    def _audit_insert(
        connection: sqlite3.Connection,
        *,
        event: str,
        operator_id: str,
        grant_id: str,
        epoch: int,
        outcome: str,
        created_at: int,
    ) -> None:
        connection.execute(
            """
            INSERT INTO grant_audit(
                event_id, event, operator_id, grant_id, epoch, outcome, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                secrets.token_hex(16),
                event,
                operator_id,
                grant_id,
                epoch,
                outcome,
                created_at,
            ),
        )

    def _lockdown_files(self) -> None:
        _chmod_best_effort(self._path, 0o600)
        _chmod_best_effort(Path(str(self._path) + "-wal"), 0o600)
        _chmod_best_effort(Path(str(self._path) + "-shm"), 0o600)


class CustodyCredentialFetcher:
    """Mint and use one short-lived Vaultwarden session per grant call."""

    supplies_material = True

    def __call__(
        self,
        grant_ref: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> CredentialMaterial:
        return self.fetch(grant_ref, deadline=deadline)

    def __init__(
        self,
        *,
        store: CustodyGrantStore,
        base_url: str,
        transport: Transport,
        device_identifier: str = "cloudbrowser-grant-broker",
    ) -> None:
        self._store = store
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._device_identifier = _bounded_text(device_identifier, "device_identifier")
        parsed = urllib.parse.urlsplit(self._base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("vault base URL must be an absolute HTTP(S) URL")

    def fetch(
        self,
        grant_ref: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> CredentialMaterial:
        with self._store.checkout(grant_ref) as lease:
            if deadline is not None:
                deadline.check()
            lease.recheck()
            token, rotated = self._mint_session(lease, deadline=deadline)
            lease.recheck()
            sync = self._sync(token, lease, deadline=deadline)
            lease.recheck()
            if rotated is not None and rotated != lease.refresh_token:
                lease.rotate_refresh_token(rotated)
            lease.recheck()
            cipher = _resolve_cipher(sync, lease.item_ref, lease.vault_key)
            material = _decrypt_cipher(cipher, lease.vault_key)
            lease.recheck()
            return material

    def run_authorized(
        self,
        authorization: GrantAuthorization,
        operation: Callable[[CredentialMaterial], _Result],
        *,
        deadline: BrokerDeadline | None = None,
    ) -> _Result:
        """Run one browser side effect under the scope's revocation lock."""
        expected = _parse_grant_ref(authorization.username_ref)
        operation_context = (
            self._store.authorized_operation(authorization.username_ref)
            if deadline is None
            else self._store.authorized_operation(
                authorization.username_ref,
                deadline=deadline,
            )
        )
        with operation_context as lease:
            if deadline is not None:
                deadline.check()
            if lease._grant_id != expected:
                raise GrantRevoked("grant revoked")
            if lease.epoch != authorization.epoch or not lease.scope.permits_request_scope(GrantScope(
                profile_id=authorization.profile_id,
                principal_id=authorization.principal_id,
                site_id=authorization.site_id,
                target_tab_id=authorization.target_tab_id,
                browser_id=authorization.browser_id,
                generation=authorization.generation,
            )):
                raise AuthorizationChanged("grant changed")
            lease.recheck()
            token, rotated = self._mint_session(lease, deadline=deadline)
            lease.recheck()
            sync = self._sync(token, lease, deadline=deadline)
            lease.recheck()
            if rotated is not None and rotated != lease.refresh_token:
                lease.rotate_refresh_token(rotated)
            lease.recheck()
            cipher = _resolve_cipher(sync, lease.item_ref, lease.vault_key)
            material = _decrypt_cipher(cipher, lease.vault_key)
            lease.recheck()
            try:
                result = operation(material)
            finally:
                material = None
            lease.recheck()
            return result

    def _call(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        deadline: BrokerDeadline | None = None,
    ) -> tuple[int, bytes]:
        try:
            return invoke_transport(
                self._transport,
                method,
                self._base_url + path,
                headers=dict(headers or {}),
                body=body,
                deadline=deadline,
            )
        except (OSError, TimeoutError, ValueError) as exc:
            raise DependencyUnavailable("vault dependency is unavailable") from exc

    def _mint_session(
        self,
        lease: GrantLease,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> tuple[str, bytes | None]:
        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": lease.refresh_token.decode("utf-8"),
                "client_id": "web",
                "deviceType": "12",
                "deviceIdentifier": self._device_identifier,
                "deviceName": "cloudbrowser-grant-broker",
            }
        ).encode("utf-8")
        status, payload = self._call(
            "POST",
            "/identity/connect/token",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            body=body,
            deadline=deadline,
        )
        if status in {400, 401}:
            lease.invalidate()
            lease.commit_invalidation()
            raise GrantRevoked("grant revoked")
        if status != 200:
            raise DependencyUnavailable("vault dependency is unavailable")
        try:
            document = json.loads(payload.decode("utf-8"))
            access = document.get("access_token")
            rotated = document.get("refresh_token")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise DependencyUnavailable("vault dependency is unavailable") from exc
        if not isinstance(access, str) or not access:
            lease.invalidate()
            lease.commit_invalidation()
            raise GrantRevoked("grant revoked")
        rotated_bytes: bytes | None = None
        if rotated is not None:
            if not isinstance(rotated, str):
                raise DependencyUnavailable("vault dependency is unavailable")
            rotated_bytes = rotated.encode("utf-8")
            _validate_refresh_token(rotated_bytes)
        return access, rotated_bytes

    def _sync(
        self,
        access_token: str,
        lease: GrantLease,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> dict:
        lease.recheck()
        status, payload = self._call(
            "GET",
            "/api/sync",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            deadline=deadline,
        )
        if status == 401:
            lease.invalidate()
            lease.commit_invalidation()
            raise GrantRevoked("grant revoked")
        if status != 200:
            raise DependencyUnavailable("vault dependency is unavailable")
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DependencyUnavailable("vault dependency is unavailable") from exc
        if not isinstance(document, dict):
            raise DependencyUnavailable("vault dependency is unavailable")
        rotated = _take_rotated_refresh_token(lease)
        if rotated is not None:
            document["__rotated_refresh_token"] = rotated
        return document


def _take_rotated_refresh_token(lease: GrantLease) -> bytes | None:
    value = lease._rotated_refresh_token
    lease._rotated_refresh_token = None
    if value is None:
        return None
    raw = bytes(value)
    GrantLease._wipe(value)
    return raw


# -- authenticated wrapping -------------------------------------------------


def _wrap(plaintext: bytes, key: bytes, aad: bytes) -> tuple[bytes, bytes, bytes]:
    if not isinstance(plaintext, bytes) or not plaintext:
        raise GrantMaterialError("cannot wrap empty material")
    iv = secrets.token_bytes(12)
    ciphertext, tag = crypto.aes_gcm_encrypt(key, iv, plaintext, aad)
    return iv, ciphertext, tag


def _unwrap(key: bytes, envelope: _Envelope, aad: bytes) -> bytes:
    if not envelope.nonce or envelope.ciphertext is None or envelope.tag is None:
        raise GrantMaterialError("incomplete grant envelope")
    return crypto.aes_gcm_decrypt(
        key,
        envelope.nonce,
        envelope.ciphertext,
        envelope.tag,
        aad,
    )


def _envelope(values: tuple[object, ...]) -> _Envelope:
    if len(values) != 3 or any(not isinstance(value, bytes) for value in values):
        raise GrantMaterialError("incomplete grant envelope")
    return _Envelope(values[0], values[1], values[2])  # type: ignore[arg-type]


def _aad(grant_id: str, scope: GrantScope, leg: str) -> bytes:
    return b"cloudbrowser.grant.v1|" + grant_id.encode("ascii") + b"|" + scope.canonical() + b"|" + leg.encode("ascii")


def _scope_values(scope: GrantScope) -> tuple[str, ...]:
    return (
        scope.profile_id,
        scope.principal_id,
        scope.site_id,
        scope.target_tab_id,
        scope.browser_id,
        scope.generation,
    )


def _scope_dict(scope: GrantScope) -> dict[str, str]:
    return {
        "profile_id": scope.profile_id,
        "principal_id": scope.principal_id,
        "site_id": scope.site_id,
        "target_tab_id": scope.target_tab_id,
        "browser_id": scope.browser_id,
        "generation": scope.generation,
    }


def _grant_ref(grant_id: str) -> str:
    encoded = base64.urlsafe_b64encode(grant_id.encode("ascii")).decode("ascii").rstrip("=")
    return _GRANT_REF_PREFIX + encoded


def _parse_grant_ref(value: str) -> str:
    if not isinstance(value, str) or not value.startswith(_GRANT_REF_PREFIX):
        raise GrantRevoked("grant revoked")
    encoded = value[len(_GRANT_REF_PREFIX) :]
    if not encoded or len(encoded) > 128 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in encoded):
        raise GrantRevoked("grant revoked")
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise GrantRevoked("grant revoked") from exc
    if not decoded or len(decoded) > 128:
        raise GrantRevoked("grant revoked")
    return decoded


def _inspect_database_schema(path: Path) -> dict[str, object] | None:
    """Read only the SQLite catalog before any schema-changing operation."""
    if not path.exists():
        return None
    try:
        with sqlite3.connect(path) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            metadata = None
            if "grant_metadata" in tables:
                columns = [
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(grant_metadata)").fetchall()
                ]
                if columns == ["schema_id", "schema_version"]:
                    metadata = connection.execute(
                        "SELECT schema_id, schema_version FROM grant_metadata"
                    ).fetchone()
            return {"tables": tables, "metadata": metadata}
    except sqlite3.DatabaseError as exc:
        raise RuntimeError("grant custody database is unreadable") from exc


def _validate_custody_schema(schema: dict[str, object]) -> None:
    tables = schema["tables"]
    if not isinstance(tables, set):
        raise RuntimeError("grant custody schema inspection failed")
    if "grants" in tables:
        raise RuntimeError(
            "prior grants table detected; use offline migrate command and reprovision grants"
        )
    required = {"grant_custody", "grant_audit", "grant_metadata"}
    if not required.issubset(tables):
        raise RuntimeError("missing custody schema metadata; refusing implicit upgrade")
    metadata = schema["metadata"]
    if not isinstance(metadata, tuple) or len(metadata) != 2:
        raise RuntimeError("missing custody schema metadata; refusing implicit upgrade")
    schema_id, version = metadata
    if schema_id != _SCHEMA_ID or version != _SCHEMA_VERSION:
        raise RuntimeError("unsupported custody schema version")


def backup_database(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
    """Create a consistent SQLite backup without mutating the source."""
    source_path = Path(source)
    destination_path = Path(destination)
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("backup destination must differ from source")
    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source_connection:
        with sqlite3.connect(destination_path) as destination_connection:
            source_connection.backup(destination_connection)
    _chmod_best_effort(destination_path, 0o600)


def rollback_database(
    current: str | os.PathLike[str],
    backup: str | os.PathLike[str],
    current_backup: str | os.PathLike[str],
) -> None:
    """Atomically replace a custody DB after backing up the current DB."""
    current_path = Path(current)
    backup_path = Path(backup)
    current_backup_path = Path(current_backup)
    if current_path.resolve() == backup_path.resolve():
        raise ValueError("rollback backup must differ from current database")
    if current_path.resolve() == current_backup_path.resolve():
        raise ValueError("current backup must differ from current database")
    schema = _inspect_database_schema(backup_path)
    if schema is None:
        raise RuntimeError("rollback backup does not exist")
    _validate_custody_schema(schema)
    backup_database(current_path, current_backup_path)
    current_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=current_path.parent, prefix=f".{current_path.name}.rollback-", delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        backup_database(backup_path, temporary_path)
        os.replace(temporary_path, current_path)
        _chmod_best_effort(current_path, 0o600)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    for suffix in ("-wal", "-shm"):
        _safe_unlink(Path(str(current_path) + suffix))


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _bounded_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_TEXT_BYTES
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{label} is invalid")
    return value


def _validate_kek(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("grant KEK must be exactly 32 bytes")
    return bytes(value)


def _validate_vault_key(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 64:
        raise ValueError("vault key must be exactly 64 bytes")
    return bytes(value)


def _validate_refresh_token(value: bytes) -> bytes:
    if (
        not isinstance(value, bytes)
        or not value
        or len(value) > _MAX_REFRESH_TOKEN_BYTES
        or any(byte in {0, 10, 13} for byte in value)
    ):
        raise ValueError("refresh token is invalid")
    return bytes(value)


def _validate_item_ref(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_ITEM_REF_BYTES
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError("item_ref is invalid")
    return value


def _token_bytes(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, (bytes, bytearray)):
        raise GrantMaterialError("rotated session leg is invalid")
    return _validate_refresh_token(bytes(value))


def parse_kek(value: str) -> bytes:
    """Parse only explicit/fully-qualified 32-byte hex KEK input."""
    if not isinstance(value, str):
        raise ValueError("grant KEK must be 64 hexadecimal characters")
    text = value[4:] if value.startswith("hex:") else value
    if len(text) != 64:
        raise ValueError("grant KEK must be 64 hexadecimal characters")
    try:
        raw = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError("grant KEK must be hexadecimal") from exc
    return _validate_kek(raw)


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        if path.exists():
            os.chmod(path, mode)
    except OSError:
        pass


# -- broker-only Vaultwarden sync/decrypt ----------------------------------


def _resolve_cipher(sync: Mapping[str, object], item_ref: str, user_key: bytes) -> Mapping[str, object]:
    raw_ciphers = sync.get("ciphers") or []
    if not isinstance(raw_ciphers, (list, tuple)):
        raise GrantMaterialError("vault sync ciphers are invalid")
    ciphers = [
        cipher
        for cipher in raw_ciphers
        if isinstance(cipher, Mapping) and cipher.get("type") == 1
    ]
    exact = [cipher for cipher in ciphers if str(cipher.get("id") or "") == item_ref]
    if len(exact) == 1:
        return exact[0]
    if item_ref.startswith("uri:"):
        prefix = item_ref[4:]
        matches = []
        for cipher in ciphers:
            resolved = _decrypt_cipher_fields(cipher, user_key)
            if any(uri.startswith(prefix) for uri in resolved[2]):
                matches.append(cipher)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise LookupError("grant unavailable")
        raise GrantMaterialError("grant item is ambiguous")
    named = [
        cipher
        for cipher in ciphers
        if _decrypt_name(cipher, user_key) == item_ref
    ]
    if len(named) == 1:
        return named[0]
    if not named:
        raise LookupError("grant unavailable")
    raise GrantMaterialError("grant item is ambiguous")


def _decrypt_name(cipher: Mapping[str, object], user_key: bytes) -> str:
    raw = cipher.get("name")
    if not raw:
        return ""
    try:
        return crypto.decrypt_encstring(str(raw), user_key)
    except crypto.VaultCryptoError as exc:
        raise GrantMaterialError("grant item cannot be decrypted") from exc


def _decrypt_cipher_fields(
    cipher: Mapping[str, object], user_key: bytes
) -> tuple[str, str, tuple[str, ...]]:
    login = cipher.get("login") or {}
    if not isinstance(login, Mapping):
        login = {}

    def decrypt(value: object) -> str:
        if not value:
            return ""
        try:
            return crypto.decrypt_encstring(str(value), user_key)
        except crypto.VaultCryptoError as exc:
            raise GrantMaterialError("grant item cannot be decrypted") from exc

    username = decrypt(login.get("username"))
    password = decrypt(login.get("password"))
    uris = tuple(
        uri
        for entry in (login.get("uris") or [])
        if isinstance(entry, Mapping)
        for uri in [decrypt(entry.get("uri"))]
        if uri
    )
    return username, password, uris


def _decrypt_cipher(cipher: Mapping[str, object], user_key: bytes) -> CredentialMaterial:
    username, password, _uris = _decrypt_cipher_fields(cipher, user_key)
    return CredentialMaterial(username=username, password=password)


__all__ = [
    "CustodyCredentialFetcher",
    "CustodyGrantStore",
    "GrantCustodyError",
    "GrantLease",
    "GrantMaterialError",
    "GrantRevoked",
    "GrantScope",
    "ProvisionedGrant",
    "backup_database",
    "parse_kek",
    "rollback_database",
]
