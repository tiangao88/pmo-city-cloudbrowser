"""Test helpers for exercising the capability-only broker boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from cloudbrowser.credential_broker import GrantAuthorization, LoginIntent
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.credential_capability import CapabilityCodec, CredentialCapability

TEST_CAPABILITY_SECRET = b"test-capability-secret-0123456789"
TEST_AUDIENCE = "credential-broker"


def configure_capability_env(
    monkeypatch,
    tmp_path: Path,
    *,
    deployment: str,
    username_ref: str,
) -> Path:
    del username_ref
    nonce_path = tmp_path / "credential-capability-nonces.sqlite3"
    monkeypatch.setenv("CB_CREDENTIAL_CAPABILITY_SECRET", TEST_CAPABILITY_SECRET.decode())
    monkeypatch.setenv("CB_CREDENTIAL_BROKER_AUDIENCE", TEST_AUDIENCE)
    monkeypatch.setenv("CB_BROKER_GRANT_DB_PATH", str(tmp_path / "broker-grants.sqlite3"))
    monkeypatch.setenv(
        "CB_BROKER_IDEMPOTENCY_DB_PATH", str(tmp_path / "broker-idempotency.sqlite3")
    )
    monkeypatch.setenv("CB_CREDENTIAL_NONCE_DB_PATH", str(nonce_path))
    monkeypatch.setenv("CB_INSTANCE_ID", deployment)
    return nonce_path


def full_grant(
    username_ref: str,
) -> Callable[[ResolvedBinding, str, str], GrantAuthorization]:
    def resolve(
        binding: ResolvedBinding,
        site_id: str,
        target_tab_id: str,
    ) -> GrantAuthorization:
        return GrantAuthorization(
            username_ref=username_ref,
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
            site_id=site_id,
            target_tab_id=target_tab_id,
        )

    return resolve


def exact_target_preflight(url: str = "https://login.example.test/"):
    def preflight(intent: LoginIntent, _declaration: object) -> object:
        return (intent.target_tab_id, url)

    return preflight


def capability_payload(
    *,
    deployment: str,
    profile_id: str,
    principal_id: str,
    browser_id: str,
    generation: str,
    site_id: str,
    target_tab_id: str,
    request_id: str,
    nonce: str,
    now: int = 1000,
) -> dict[str, str]:
    capability = CredentialCapability(
        profile_id=profile_id,
        principal_id=principal_id,
        browser_id=browser_id,
        generation=generation,
        site_id=site_id,
        target_tab_id=target_tab_id,
        operation="credential.login",
        request_id=request_id,
        audience=TEST_AUDIENCE,
        deployment=deployment,
        issued_at=now,
        expires_at=now + 30,
        nonce=nonce,
    )
    return {"capability": CapabilityCodec(TEST_CAPABILITY_SECRET).encode(capability)}


def nonce_store(path: Path) -> DurableNonceStore:
    return DurableNonceStore(path)
