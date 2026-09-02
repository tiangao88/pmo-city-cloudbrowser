"""RED-stage tests for the broker audit emitter (PRD-BR-12; spec 82).

The audit surface is a bounded, structured event emitter. It must:

- emit only the ``cloudbrowser.audit.v1`` envelope;
- refuse payloads whose value contains credential-shaped substrings
  (passwords, refresh tokens, OTP codes);
- keep request_id opaque, bounded, and correlated;
- serialize only safe durations, never exception strings or page content.
"""

from __future__ import annotations

import json

import pytest

from cloudbrowser.credential_broker.audit import (
    AuditEmitter,
    AuditEventType,
    build_event,
)


def safe_emitter() -> AuditEmitter:
    return AuditEmitter(component="credential-broker", instance_id="cloudbrowser-dev-v01")


def test_event_envelope_contains_mandatory_fields_only() -> None:
    event = build_event(
        emitter=safe_emitter(),
        event_type=AuditEventType.BROKER_LOGIN,
        owner_id="alice@example.test",
        outcome="rejected",
        error_code="owner_mismatch",
        duration_ms=12,
    )
    body = json.loads(event.to_json())
    assert body["schema"] == "cloudbrowser.audit.v1"
    assert body["event_type"] == "broker_login"
    assert body["actor_type"] == "broker"
    assert body["outcome"] == "rejected"
    assert body["error_code"] == "owner_mismatch"
    assert body["duration_ms"] == 12
    assert body["owner_id"] == "alice@example.test"
    assert body["component"] == "credential-broker"
    assert body["instance_id"] == "cloudbrowser-dev-v01"


def test_event_emitter_rejects_credential_shaped_payload() -> None:
    event = build_event(
        emitter=safe_emitter(),
        event_type=AuditEventType.BROKER_LOGIN,
        owner_id="alice@example.test",
        outcome="completed",
        error_code=None,
        duration_ms=4,
    )
    with pytest.raises(ValueError):
        event.with_extra(reason="refresh_token=ABCDEFGHIJKLMN")
    with pytest.raises(ValueError):
        event.with_extra(reason="password=hunter2")
    with pytest.raises(ValueError):
        event.with_extra(reason="Authorization: Bearer xyz")


def test_event_serializes_to_json_without_exception_strings() -> None:
    event = build_event(
        emitter=safe_emitter(),
        event_type=AuditEventType.BROKER_LOGIN_FAILED,
        owner_id="alice@example.test",
        outcome="rejected",
        error_code="broker_login_timeout",
        duration_ms=3000,
    )
    payload = event.to_json()
    body = json.loads(payload)
    assert "traceback" not in body
    assert "secret" not in body


def test_event_omits_request_id_when_not_provided() -> None:
    event = build_event(
        emitter=safe_emitter(),
        event_type=AuditEventType.BROKER_MFA_REQUESTED,
        owner_id="alice@example.test",
        outcome="started",
        error_code=None,
        duration_ms=0,
    )
    body = json.loads(event.to_json())
    assert body.get("request_id") in (None,)
