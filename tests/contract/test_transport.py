"""RED-stage tests for the credential-broker transport (PRD-BR-01 / S3 attack
case "Agent alters principal_id" / "Agent replays nonce").

The transport must:

- only accept the intent-only request shape;
- reject any caller-supplied principal_id that differs from the
  server-authenticated identity (PRD-BR-03, S3, attack-case row 3);
- never serialize a credential value, refresh token, OTP, cookie value,
  authorization header, or raw exception back to the agent;
- bind every response to the server-issued request_id, never an agent one;
- replay the idempotent status when (principal, idempotency_key) match.

These tests use an in-memory HTTP client (the agent surface is JSON over
HTTPS in production but we keep the harness dependency-free here).
"""

from __future__ import annotations

import json

import pytest

from cloudbrowser.credential_broker.api import (
    AuthenticatedPrincipal,
    BrokerHttpServer,
    ServerIdentity,
)


def _principal(principal_id: str = "alice@example.test") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        profile_id="profile-a",
        principal_id=principal_id,
        browser_id="browser-1",
        site_id="site-a",
        generation="g1",
    )


def _server() -> BrokerHttpServer:
    return BrokerHttpServer(
        server_identity=ServerIdentity(component="credential-broker", instance_id="cloudbrowser-dev-v01"),
        principal_for=lambda auth_token: _principal(),
    )


def test_login_returns_only_status_to_agent() -> None:
    server = _server()
    request = {
        "request_id": "req-1",
        "auth_token": "fake-opaque-session",
        "username_ref": "acct-1",
        "site_id": "site-a",
        "current_url": "https://login.example.test/start",
    }
    with server.handle("/v1/credential/login", request) as response:
        body = response.body
        for forbidden in ("password", "token", "cookie", "secret"):
            assert forbidden not in json.dumps(body).lower()
        assert set(body.keys()) == {"request_id", "status", "error_code", "duration_ms"}


def test_login_rejects_caller_overridden_principal_id() -> None:
    server = BrokerHttpServer(
        server_identity=ServerIdentity(component="credential-broker", instance_id="cloudbrowser-dev-v01"),
        principal_for=lambda auth_token: _principal(principal_id="alice@example.test"),
    )
    request = {
        "request_id": "req-2",
        "auth_token": "fake-opaque-session",
        "username_ref": "acct-1",
        "site_id": "site-a",
        "current_url": "https://login.example.test/start",
        "principal_id": "bob@example.test",
    }
    with server.handle("/v1/credential/login", request) as response:
        assert response.body["status"] == "failed"
        assert response.body["error_code"] == "binding_mismatch"
        assert "bob@example.test" not in json.dumps(response.body)


def test_login_replays_idempotent_result() -> None:
    server = _server()
    request = {
        "request_id": "req-3",
        "auth_token": "fake-opaque-session",
        "username_ref": "acct-1",
        "site_id": "site-a",
        "current_url": "https://login.example.test/start",
        "idempotency_key": "idem-9",
    }
    with server.handle("/v1/credential/login", request) as first:
        with server.handle("/v1/credential/login", request) as second:
            assert first.body["status"] == second.body["status"]
            assert second.body["request_id"] == request["request_id"]


def test_login_path_mismatch_returns_404() -> None:
    server = _server()
    with pytest.raises(LookupError):
        with server.handle("/v1/unknown", {}):
            pass


def test_login_request_validation_returns_structured_error() -> None:
    server = _server()
    request = {
        "request_id": "",
        "auth_token": "fake",
        "username_ref": "acct-1",
        "site_id": "site-a",
        "current_url": "https://login.example.test/start",
    }
    with server.handle("/v1/credential/login", request) as response:
        assert response.body["status"] == "failed"
        assert response.body["error_code"] == "invalid_request"
