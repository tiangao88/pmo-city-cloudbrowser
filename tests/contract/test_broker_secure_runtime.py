"""Runtime assembly security requirements for capability login."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.runtime import LiveBrowserBinding, build_broker_api


class _Browser:
    def live_binding(self) -> LiveBrowserBinding:
        return LiveBrowserBinding("profile-a", "principal-a", "browser-a", "generation-a")

    def current_url(self, *, target_id: str) -> str:
        return "https://login.example.test/"


def _base_env(monkeypatch) -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "deployment-a")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "basic")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "site-a")
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://login.example.test")
    monkeypatch.setenv("CB_BROKER_SUCCESS_PATH", "/home")
    monkeypatch.setenv("CB_BROKER_SUBMIT_SECRET", "submit-secret-0123456789")
    monkeypatch.setenv("CB_CREDENTIAL_CAPABILITY_SECRET", "capability-secret-0123456789")
    monkeypatch.setenv("CB_CREDENTIAL_BROKER_AUDIENCE", "credential-broker")
    monkeypatch.setenv("CB_BROKER_GRANT_DB_PATH", "/tmp/test-grants.sqlite3")
    monkeypatch.setenv("CB_BROKER_IDEMPOTENCY_DB_PATH", "/tmp/test-idempotency.sqlite3")


def _build(tmp_path: Path):
    return build_broker_api(
        browser_factory=_Browser,
        credential_fetcher=lambda _: CredentialMaterial("alice", "secret"),
        nonce_store=DurableNonceStore(tmp_path / "nonces.sqlite3"),
        idempotency_store=DurableIdempotencyStore(tmp_path / "idempotency.sqlite3"),
    )


def test_runtime_requires_capability_secret(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("CB_CREDENTIAL_CAPABILITY_SECRET")
    with pytest.raises(SystemExit, match="CB_CREDENTIAL_CAPABILITY_SECRET"):
        _build(tmp_path)


def test_runtime_requires_explicit_audience(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("CB_CREDENTIAL_BROKER_AUDIENCE")
    with pytest.raises(SystemExit, match="CB_CREDENTIAL_BROKER_AUDIENCE"):
        _build(tmp_path)


def test_runtime_requires_explicit_deployment_or_instance(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("CB_INSTANCE_ID")
    monkeypatch.delenv("CB_DEPLOYMENT", raising=False)
    with pytest.raises(SystemExit, match="CB_DEPLOYMENT or CB_INSTANCE_ID"):
        _build(tmp_path)


def test_runtime_requires_server_owned_grant_configuration(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch)
    monkeypatch.delenv("CB_BROKER_GRANT_DB_PATH")
    with pytest.raises(SystemExit, match="CB_BROKER_GRANT_DB_PATH"):
        _build(tmp_path)
