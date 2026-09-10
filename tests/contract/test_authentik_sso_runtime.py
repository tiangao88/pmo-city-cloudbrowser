"""Authentik SSO runtime stops safely at the human MFA checkpoint."""

from __future__ import annotations

import pytest

from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability
from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.adapters.sso import (
    AuthentikSSOAdapter,
    AuthentikSSODeclaration,
)
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded


def test_sso_adapter_stops_before_identification_when_budget_expires_during_state_probe() -> None:
    class ExpiringBrowser:
        def current_url(self) -> str:
            return "https://auth.example.test/if/flow/login/"

        def begin_authentik(self, entry_url: str) -> None:
            raise AssertionError("navigation is not expected")

        def mfa_stage(self) -> None:
            clock[0] = 3.0
            return None

        def identification(self, username: str, password: str) -> str:
            raise AssertionError("credential side effect must not start after deadline")

        def application_identity(self) -> None:
            return None

    clock = [1.0]
    deadline = BrokerDeadline(2.0, monotonic_clock=lambda: clock[0])
    declaration = AuthentikSSODeclaration(
        site_id="sso",
        entry_url="https://auth.example.test/if/flow/login/",
        idp_origins=("https://auth.example.test",),
        callback_origins=("https://app.example.test",),
        application_origins=("https://app.example.test",),
        application_success_paths=("/home",),
    )
    with pytest.raises(BrokerDeadlineExceeded):
        AuthentikSSOAdapter().execute(
            declaration,
            CredentialMaterial("alice", "secret"),
            ExpiringBrowser(),
            expected_account="alice",
            deadline=deadline,
        )


from cloudbrowser.credential_broker.grant_store import DurableGrantStore
from cloudbrowser.credential_broker.runtime import LiveBrowserBinding, build_broker_api


class _AuthentikBrowser:
    def __init__(self) -> None:
        self.url = "https://auth.example.test/if/flow/default-authentication-flow/"
        self.identifications: list[tuple[str, str]] = []

    def live_binding(self) -> LiveBrowserBinding:
        return LiveBrowserBinding("profile-a", "pmo-a", "browser-1", "g1")

    def current_url(self, *, target_id: str | None = None) -> str:
        if target_id is not None:
            assert target_id == "target-1"
        return self.url

    def begin_authentik(self, entry_url: str) -> None:
        self.url = entry_url

    def identification(self, username: str, password: str) -> str:
        self.identifications.append((username, password))
        return "submitted"

    def mfa_stage(self) -> str | None:
        return "totp" if self.identifications else None

    def application_identity(self) -> str | None:
        return None


def test_sso_runtime_returns_mfa_required_without_submitting_mfa(monkeypatch, tmp_path) -> None:
    values = {
        "CB_INSTANCE_ID": "test",
        "CB_RELEASE_VERSION": "test",
        "CB_BROKER_SHARED_SECRET": "broker-secret-0123456789abcdef",
        "CB_BROKER_SUBMIT_SECRET": "submit-secret-0123456789abcdef",
        "CB_CREDENTIAL_CAPABILITY_SECRET": "capability-secret-0123456789abcdef",
        "CB_CREDENTIAL_BROKER_AUDIENCE": "credential-broker",
        "CB_BROKER_GRANT_DB_PATH": str(tmp_path / "grants.sqlite3"),
        "CB_BROKER_IDEMPOTENCY_DB_PATH": str(tmp_path / "idempotency.sqlite3"),
        "CB_CREDENTIAL_NONCE_DB_PATH": str(tmp_path / "nonces.sqlite3"),
        "CB_BROKER_SSO_IDENTITY_SELECTOR": "[data-account-id]",
        "CB_BROKER_SSO_IDENTITY_CLAIM": "attribute:data-account-id",
        "CB_BROKER_ADAPTER": "sso",
        "CB_BROKER_SITE_ID": "authentik-test",
        "CB_BROKER_ORIGIN": "https://auth.example.test",
        "CB_BROKER_SSO_ENTRY_URL": "https://auth.example.test/if/flow/default-authentication-flow/",
        "CB_BROKER_SSO_IDP_ORIGINS": "https://auth.example.test",
        "CB_BROKER_SSO_CALLBACK_ORIGINS": "https://app.example.test",
        "CB_BROKER_SSO_APPLICATION_ORIGINS": "https://app.example.test",
        "CB_BROKER_SSO_SUCCESS_PATHS": "/authenticated",
        "CB_BROKER_SSO_ALLOWED_MFA": "totp",
        "CB_BROKER_SSO_STAGE_TIMEOUT_S": "29",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    browser = _AuthentikBrowser()
    capability = CapabilityCodec(values["CB_CREDENTIAL_CAPABILITY_SECRET"]).encode(
        CredentialCapability(
            profile_id="profile-a",
            principal_id="pmo-a",
            browser_id="browser-1",
            generation="g1",
            site_id="authentik-test",
            target_tab_id="target-1",
            operation="credential.login",
            request_id="req-sso",
            audience="credential-broker",
            deployment="test",
            issued_at=1,
            expires_at=61,
            nonce="nonce-sso-1",
        )
    )
    grants = DurableGrantStore(tmp_path / "grants.sqlite3")
    grants.put(
        profile_id="profile-a",
        principal_id="pmo-a",
        site_id="authentik-test",
        target_tab_id="target-1",
        browser_id="browser-1",
        generation="g1",
        username_ref="authentik-item",
    )
    api = build_broker_api(
        browser_factory=lambda: browser,
        credential_fetcher=lambda _ref: CredentialMaterial("alice", "secret-pw"),
        grant_resolver=grants,
        clock=lambda: 1,
    )

    with api.handle(
        "/v1/credential/login",
        {"capability": capability},
    ) as response:
        body = dict(response.body)

    assert body == {
        "request_id": "req-sso",
        "status": "mfa_required",
        "error_code": "mfa_required",
        "duration_ms": 0,
    }
    assert browser.identifications == [("alice", "secret-pw")]
