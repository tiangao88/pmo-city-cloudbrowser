"""Broker audit envelope (`cloudbrowser.audit.v1`).

Spec 82 bounds the envelope. The emitter rejects any payload that smells
like a credential — passwords, refresh tokens, OTP codes, authorization
headers — at the constructor boundary. The serialized form is JSON with
only the allowlisted fields.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


_FORBIDDEN_SHAPES = (
    re.compile(r"(?i)password\s*[:=]\s*\S+"),
    re.compile(r"(?i)refresh[_-]?token\s*[:=]\s*\S+"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+"),
    re.compile(r"\botp\s*[:=]\s*\d{4,8}\b"),
    re.compile(r"(?i)\baccess[_-]?token\s*[:=]\s*\S+"),
)


class AuditEventType(str, Enum):
    BROKER_LOGIN = "broker_login"
    BROKER_LOGIN_FAILED = "broker_login_failed"
    BROKER_MFA_REQUESTED = "broker_mfa_requested"
    BROKER_MFA_RESOLVED = "broker_mfa_resolved"
    BROKER_REVOKED = "broker_revoked"
    BROKER_OWNER_MISMATCH = "broker_owner_mismatch"


@dataclass(frozen=True)
class AuditEmitter:
    component: str
    instance_id: str


def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event(
    *,
    emitter: AuditEmitter,
    event_type: AuditEventType,
    owner_id: str,
    outcome: str,
    error_code: str | None,
    duration_ms: int,
    request_id: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> "AuditEvent":
    return AuditEvent(
        emitter=emitter,
        event_type=event_type,
        owner_id=owner_id,
        outcome=outcome,
        error_code=error_code,
        duration_ms=duration_ms,
        request_id=request_id,
        extra=dict(extra) if extra else None,
    )


@dataclass(frozen=True)
class AuditEvent:
    emitter: AuditEmitter
    event_type: AuditEventType
    owner_id: str
    outcome: str
    error_code: str | None
    duration_ms: int
    request_id: str | None = None
    extra: dict[str, str] | None = None
    event_at: str = field(default_factory=_now_iso)

    def with_extra(self, **values: str) -> "AuditEvent":
        merged: dict[str, str] = dict(self.extra or {})
        for key, val in values.items():
            if _looks_like_credential(val):
                raise ValueError(f"audit.extra value rejected: {key}")
            merged[key] = val
        return AuditEvent(
            emitter=self.emitter,
            event_type=self.event_type,
            owner_id=self.owner_id,
            outcome=self.outcome,
            error_code=self.error_code,
            duration_ms=self.duration_ms,
            request_id=self.request_id,
            extra=merged,
            event_at=self.event_at,
        )

    def to_json(self) -> str:
        body = self.body()
        return json.dumps(body, separators=(",", ":"), sort_keys=True)

    def body(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": "cloudbrowser.audit.v1",
            "event_at": self.event_at,
            "event_type": self.event_type.value,
            "actor_type": "broker",
            "owner_id": self.owner_id,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "component": self.emitter.component,
            "instance_id": self.emitter.instance_id,
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.extra:
            for k, v in self.extra.items():
                if _looks_like_credential(v):
                    raise ValueError(f"audit.extra value rejected: {k}")
                result[k] = v
        return result


def _looks_like_credential(value: str) -> bool:
    return any(pattern.search(value) for pattern in _FORBIDDEN_SHAPES)
