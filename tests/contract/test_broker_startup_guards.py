"""Startup and compose guards for production broker security state."""

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


def _env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "deployment-a")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "basic")
    monkeypatch.setenv("CB_BROKER_SITE_ID", "site-a")
    monkeypatch.setenv("CB_BROKER_ORIGIN", "https://login.example.test")
    monkeypatch.setenv("CB_BROKER_SUCCESS_PATH", "/home")
    monkeypatch.setenv("CB_BROKER_SUBMIT_SECRET", "submit-secret-0123456789")
    monkeypatch.setenv("CB_CREDENTIAL_CAPABILITY_SECRET", "capability-secret-0123456789")
    monkeypatch.setenv("CB_CREDENTIAL_BROKER_AUDIENCE", "credential-broker")
    monkeypatch.setenv("CB_BROKER_GRANT_DB_PATH", str(tmp_path / "grants.sqlite3"))
    monkeypatch.setenv("CB_BROKER_IDEMPOTENCY_DB_PATH", str(tmp_path / "idempotency.sqlite3"))


def _build(tmp_path: Path):
    return build_broker_api(
        browser_factory=_Browser,
        credential_fetcher=lambda _: CredentialMaterial("alice", "secret"),
        nonce_store=DurableNonceStore(tmp_path / "nonces.sqlite3"),
        idempotency_store=DurableIdempotencyStore(tmp_path / "injected-idempotency.sqlite3"),
    )


def test_global_username_ref_is_rejected(monkeypatch, tmp_path: Path) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("CB_BROKER_GRANT_USERNAME_REF", "global-item")
    with pytest.raises(SystemExit, match="forbidden"):
        _build(tmp_path)


def test_form_mode_fails_closed_at_startup(monkeypatch, tmp_path: Path) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("CB_BROKER_ADAPTER", "form")
    with pytest.raises(SystemExit, match="exact-target form capability"):
        _build(tmp_path)


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_compose_requires_durable_grant_and_idempotency_backends(filename: str) -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "deploy" / "coolify" / filename).read_text(encoding="utf-8")
    broker = text.split("  credential-broker:", 1)[1].split("\nnetworks:", 1)[0]
    assert "CB_BROKER_GRANT_DB_PATH: /data/state/grant-custody-v1.sqlite3" in broker
    assert "CB_BROKER_IDEMPOTENCY_DB_PATH: /data/state/idempotency.sqlite3" in broker
    assert "CB_CREDENTIAL_NONCE_DB_PATH: /data/state/nonces.sqlite3" in broker
    assert "CB_BROKER_GRANT_USERNAME_REF" not in broker


def test_coolify_compose_requires_custody_and_omits_global_vault_credentials() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "deploy" / "coolify" / "compose.coolify.yaml").read_text(
        encoding="utf-8"
    )
    broker = text.split("  credential-broker:", 1)[1].split("\nnetworks:", 1)[0]
    assert "CB_BROKER_GRANT_KEK_HEX: ${CB_BROKER_GRANT_KEK_HEX:?" in broker
    assert "CB_VAULT_BASE_URL: ${CB_VAULT_BASE_URL:?" in broker
    assert "CB_VAULT_EMAIL" not in broker
    assert "CB_VAULT_PASSWORD" not in broker
