"""Capability-only credential-broker transport contracts."""

from __future__ import annotations

import json

import pytest

from cloudbrowser.credential_broker.api import BrokerHttpServer, ServerIdentity
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore


def _unconfigured_server() -> BrokerHttpServer:
    return BrokerHttpServer(
        server_identity=ServerIdentity(
            component="credential-broker",
            instance_id="cloudbrowser-dev-v01",
        )
    )


def test_login_rejects_legacy_request_without_echoing_sensitive_fields() -> None:
    server = _unconfigured_server()
    request = {
        "request_id": "req-1",
        "auth_token": "fake-opaque-session",
        "username_ref": "acct-1",
        "site_id": "site-a",
        "current_url": "https://login.example.test/start",
        "target_tab_id": "target-1",
    }
    with server.handle("/v1/credential/login", request) as response:
        body = response.body
    assert body["status"] == "failed"
    assert body["error_code"] == "invalid_request"
    for forbidden in ("password", "token", "cookie", "secret", "acct-1"):
        assert forbidden not in json.dumps(body).lower()
    assert set(body) == {"request_id", "status", "error_code", "duration_ms"}


def test_login_rejects_caller_overridden_principal_id_as_invalid_schema() -> None:
    server = _unconfigured_server()
    with server.handle(
        "/v1/credential/login",
        {"capability": "opaque", "principal_id": "bob@example.test"},
    ) as response:
        assert response.body["status"] == "failed"
        assert response.body["error_code"] == "invalid_request"
        assert "bob@example.test" not in json.dumps(response.body)


def test_login_rejects_caller_idempotency_field() -> None:
    server = _unconfigured_server()
    with server.handle(
        "/v1/credential/login",
        {"capability": "opaque", "idempotency_key": "idem-9"},
    ) as response:
        assert response.body["status"] == "failed"
        assert response.body["error_code"] == "invalid_request"


def test_login_path_mismatch_returns_404() -> None:
    server = _unconfigured_server()
    with pytest.raises(LookupError):
        with server.handle("/v1/unknown", {}):
            pass


def test_login_request_validation_returns_structured_error() -> None:
    server = _unconfigured_server()
    with server.handle("/v1/credential/login", {"capability": ""}) as response:
        assert response.body["status"] == "failed"
        assert response.body["error_code"] == "invalid_request"
