"""Redacted audit and log emission for CloudFiles.

Threat T14 requires that audit and log events never carry raw filenames or
principal identifiers. This module emits only bounded codes, hashes, sizes,
and counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

from .identity import hash_principal


_RAW_PRINCIPAL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_RAW_PATH = re.compile(r"(?:/data/|/home/|/var/|/tmp/)[A-Za-z0-9._/-]+")
_RAW_FILENAME = re.compile(r"\.[A-Za-z0-9]{1,8}\b")


@dataclass(frozen=True)
class AuditEvent:
    """A bounded, redacted audit event."""

    event_code: str
    request_id: str
    principal_hash: str
    size_bytes: int | None = None
    counts: dict[str, int] | None = None
    at: str = ""

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "event_code": self.event_code,
            "request_id": self.request_id,
            "principal_hash": self.principal_hash,
            "at": self.at,
        }
        if self.size_bytes is not None:
            payload["size_bytes"] = int(self.size_bytes)
        if self.counts is not None:
            payload["counts"] = dict(self.counts)
        return payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def redact_event(event: dict[str, object]) -> dict[str, object]:
    """Return a bounded, redacted view of `event`.

    Removes any value containing an `@` (email), an absolute path, or a file
    extension. Returns a copy with only bounded fields.
    """

    safe: dict[str, object] = {}
    for key, value in event.items():
        if not isinstance(value, str):
            safe[key] = value
            continue
        if _RAW_PRINCIPAL.search(value) or _RAW_PATH.search(value):
            continue
        if _RAW_FILENAME.search(value):
            continue
        safe[key] = value
    return safe


def record_erasure(*, principal_hash: str, request_id: str) -> dict[str, object]:
    """Emit the bounded erasure audit event (no raw names, no raw principals)."""

    if not isinstance(principal_hash, str) or not principal_hash:
        raise ValueError("principal_hash must be non-empty text")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id must be non-empty text")
    return AuditEvent(
        event_code="erasure.completed",
        request_id=request_id,
        principal_hash=principal_hash,
        at=_now_iso(),
    ).as_dict()


def record_ingest(
    *,
    principal: str,
    request_id: str,
    size_bytes: int,
    outcome: str,
    scanner_status: str = "clean",
) -> dict[str, object]:
    """Emit a bounded ingest audit event."""

    if outcome not in {"published", "quarantined", "rejected"}:
        raise ValueError("outcome must be published, quarantined, or rejected")
    return AuditEvent(
        event_code=f"ingest.{outcome}",
        request_id=request_id,
        principal_hash=hash_principal(principal),
        size_bytes=size_bytes,
        counts={"scanner_status": _scanner_count(scanner_status)},
        at=_now_iso(),
    ).as_dict()


def _scanner_count(status: str) -> int:
    """Map a scanner status to a bounded integer count."""

    return {"clean": 0, "infected": 1, "error": 2}.get(status, 3)


__all__ = [
    "AuditEvent",
    "redact_event",
    "record_erasure",
    "record_ingest",
]
