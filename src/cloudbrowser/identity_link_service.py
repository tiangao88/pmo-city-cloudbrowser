"""PMO-owned identity-link storage and its internal HTTP adapter.

The link store is the sole authority that turns a trusted TinyAuth edge key
into an immutable PMO principal. It intentionally ignores email: OIDC users
are keyed by issuer + Remote-Sub, while local TinyAuth users are keyed by realm
+ Remote-User. The service generates PMO IDs itself and retains revoked links
as tombstones so an external identity can never silently acquire a new owner.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping

from .identity_links import IdentityLinkKey

_MAX_BODY_BYTES = 16 * 1024
_MAX_ID_BYTES = 256
_MAX_GROUPS = 32
_ALLOWED_NAMESPACE = {"oidc", "tinyauth-local"}
_HEALTH_PATH = "/health"


class IdentityLinkError(RuntimeError):
    """Base class for identity-link storage errors."""


class IdentityLinkStore:
    """Durable, transactional identity-link registry."""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] | None = None) -> None:
        self._path = str(path)
        self._clock = clock or time.time
        self._lock = threading.RLock()
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS identity_links (
                    namespace TEXT NOT NULL,
                    issuer_or_realm TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    pmo_user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    revoked_at REAL,
                    PRIMARY KEY (namespace, issuer_or_realm, external_id),
                    UNIQUE (pmo_user_id)
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_identity_links_pmo_user_id "
                "ON identity_links(pmo_user_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=5.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def resolve(self, key: IdentityLinkKey, *, groups: tuple[str, ...]) -> str | None:
        _validate_key(key)
        if "PMOC_Users" not in groups:
            return None
        with self._lock:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT pmo_user_id, revoked_at FROM identity_links "
                    "WHERE namespace = ? AND issuer_or_realm = ? AND external_id = ?",
                    (key.namespace, key.issuer_or_realm, key.external_id),
                ).fetchone()
                if row is not None:
                    db.execute("COMMIT")
                    return None if row["revoked_at"] is not None else str(row["pmo_user_id"])
                principal = _new_pmo_user_id()
                now = self._clock()
                db.execute(
                    "INSERT INTO identity_links "
                    "(namespace, issuer_or_realm, external_id, pmo_user_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key.namespace, key.issuer_or_realm, key.external_id, principal, now),
                )
                db.execute("COMMIT")
                return principal

    def revoke(self, key: IdentityLinkKey) -> bool:
        _validate_key(key)
        with self._lock:
            with self._connect() as db:
                cursor = db.execute(
                    "UPDATE identity_links SET revoked_at = ? "
                    "WHERE namespace = ? AND issuer_or_realm = ? AND external_id = ? "
                    "AND revoked_at IS NULL",
                    (self._clock(), key.namespace, key.issuer_or_realm, key.external_id),
                )
                return cursor.rowcount == 1


def _new_pmo_user_id() -> str:
    return f"pmo-{secrets.token_hex(16)}"


def _validate_key(key: IdentityLinkKey) -> None:
    if not isinstance(key, IdentityLinkKey) or key.namespace not in _ALLOWED_NAMESPACE:
        raise ValueError("identity key is invalid")
    for value in (key.issuer_or_realm, key.external_id):
        if not isinstance(value, str) or not value or len(value.encode()) > _MAX_ID_BYTES:
            raise ValueError("identity key value is invalid")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("identity key value is invalid")


def _validate_groups(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > _MAX_GROUPS:
        raise ValueError("groups are invalid")
    result = []
    for group in value:
        if not isinstance(group, str) or not group or len(group) > _MAX_ID_BYTES:
            raise ValueError("groups are invalid")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in group):
            raise ValueError("groups are invalid")
        result.append(group)
    return tuple(result)


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, object] | None:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        if length <= 0 or length > _MAX_BODY_BYTES:
            return None
        value = json.loads(handler.rfile.read(length))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def create_identity_link_server(
    store: IdentityLinkStore,
    *,
    shared_secret: str,
    oidc_issuer: str,
    tinyauth_realm: str,
    address: tuple[str, int] = ("127.0.0.1", 8091),
) -> ThreadingHTTPServer:
    """Create the internal-only identity resolver API."""
    if not isinstance(shared_secret, str) or len(shared_secret) < 16:
        raise ValueError("shared_secret must be at least 16 characters")
    if not isinstance(oidc_issuer, str) or not oidc_issuer or len(oidc_issuer) > _MAX_ID_BYTES:
        raise ValueError("oidc_issuer is invalid")
    if not isinstance(tinyauth_realm, str) or not tinyauth_realm or len(tinyauth_realm) > _MAX_ID_BYTES:
        raise ValueError("tinyauth_realm is invalid")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path == _HEALTH_PATH:
                self._send(200, {"status": "ok", "component": "identity-link"})
                return
            self._send(404, {"ok": False, "error_code": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path != "/v1/resolve":
                self._send(404, {"ok": False, "error_code": "not_found"})
                return
            if not secrets.compare_digest(
                self.headers.get("X-CB-Identity-Link-Secret", ""), shared_secret
            ):
                self._send(401, {"ok": False, "error_code": "unauthorized"})
                return
            body = _json_body(self)
            try:
                if body is None or "pmo_user_id" in body:
                    raise ValueError
                namespace = body["namespace"]
                issuer_or_realm = body["issuer_or_realm"]
                external_id = body["external_id"]
                groups = _validate_groups(body["groups"])
                key = IdentityLinkKey(namespace, issuer_or_realm, external_id)
                if key.namespace == "oidc" and key.issuer_or_realm != oidc_issuer:
                    raise ValueError
                if key.namespace == "tinyauth-local" and key.issuer_or_realm != tinyauth_realm:
                    raise ValueError
                principal = store.resolve(key, groups=groups)
            except (KeyError, TypeError, ValueError):
                self._send(400, {"ok": False, "error_code": "invalid_request"})
                return
            if principal is None:
                self._send(403, {"ok": False, "error_code": "forbidden"})
                return
            self._send(200, {"ok": True, "principal_id": principal})

        def _send(self, status: int, document: Mapping[str, object]) -> None:
            body = json.dumps(document, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer(address, Handler)
