"""Quota, retention, erasure, and authorization policy for CloudFiles.

Implements threat T9 (quota/retention tampering), T10 (GDPR erasure), and
T15 (no presigned URL routes, unauthenticated request rejection).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from .contracts import (
    CloudFilesError,
    Forbidden,
    NotFound,
    PrincipalBinding,
    TooLarge,
    Unauthorized,
)


DEFAULT_QUOTA_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB per principal
DEFAULT_RETENTION_DAYS = 90
DEFAULT_MAX_FILE_BYTES = 1024 * 1024 * 1024  # 1 GB single file cap
DEFAULT_MAX_TOTAL_BYTES = 5 * 1024 * 1024 * 1024  # 5 GB per request window


@dataclass(frozen=True)
class PolicyConfig:
    """Configurable policy limits for CloudFiles."""

    quota_bytes: int = DEFAULT_QUOTA_BYTES
    retention_days: int = DEFAULT_RETENTION_DAYS
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


def enforce_quota(
    *,
    principal: str,
    current_bytes: int,
    incoming_bytes: int,
    quota_bytes: int = DEFAULT_QUOTA_BYTES,
) -> None:
    """Raise TooLarge when adding `incoming_bytes` would exceed the quota."""

    if current_bytes < 0 or incoming_bytes < 0 or quota_bytes <= 0:
        raise ValueError("byte counts must be non-negative and quota must be positive")
    if current_bytes + incoming_bytes > quota_bytes:
        raise TooLarge("principal would exceed per-principal quota")


def enforce_single_file_size(
    *,
    incoming_bytes: int,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> None:
    """Raise TooLarge when the incoming file is larger than the single cap."""

    if incoming_bytes < 0 or max_file_bytes <= 0:
        raise ValueError("byte counts must be non-negative")
    if incoming_bytes > max_file_bytes:
        raise TooLarge("file exceeds the single-file cap")


def is_retrievable(
    *,
    mtime: datetime,
    now: datetime | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> bool:
    """Return False if the file is older than the retention window."""

    if mtime.tzinfo is None:
        mtime = mtime.replace(tzinfo=timezone.utc)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age = moment - mtime
    return age <= timedelta(days=retention_days)


def erase_principal(*, principal: str, store_root: Path) -> None:
    """Erase all references to `principal` under `store_root`.

    Implementation lives in `store.py`; this function is a typed policy
    surface that the red tests can call without depending on the store
    implementation details.
    """

    from .store import DownloadStore
    DownloadStore(store_root=store_root).erase(principal=principal)


def authorize_public_request(context: Mapping[str, object]) -> PrincipalBinding:
    """Authorize a public request and return the server-bound principal.

    Raises:
    - Unauthorized when there is no TinyAuth session;
    - Forbidden when the session has been revoked;
    - OwnerBindingUnavailable when the session is stale or missing
      identity information.
    """

    from .identity import TinyAuthSession, resolve_principal
    if context.get("session") is None:
        raise Unauthorized("TinyAuth session is missing")
    session = context.get("session")
    if not isinstance(session, TinyAuthSession):
        raise Unauthorized("TinyAuth session is missing")
    return resolve_principal(dict(context))


__all__ = [
    "PolicyConfig",
    "enforce_quota",
    "enforce_single_file_size",
    "is_retrievable",
    "erase_principal",
    "authorize_public_request",
    "DEFAULT_QUOTA_BYTES",
    "DEFAULT_RETENTION_DAYS",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "Unauthorized",
    "Forbidden",
]
