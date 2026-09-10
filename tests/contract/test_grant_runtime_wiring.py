"""Production GrantHub custody wiring guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.credential_broker.runtime import LiveBrowserBinding, build_broker_api


class _Browser:
    def live_binding(self) -> LiveBrowserBinding:
        return LiveBrowserBinding("profile-a", "principal-a", "browser-a", "generation-a")


def _env(monkeypatch, tmp_path: Path) -> None:
    values = {
        "CB_INSTANCE_ID": "deployment-a",
        "CB_BROKER_ADAPTER": "basic",
        "CB_BROKER_SITE_ID": "site-a",
        "CB_BROKER_ORIGIN": "https://login.example.test",
        "CB_BROKER_SUCCESS_PATH": "/home",
        "CB_BROKER_SUBMIT_SECRET": "submit-secret-0123456789",
        "CB_CREDENTIAL_CAPABILITY_SECRET": "capability-secret-0123456789",
        "CB_CREDENTIAL_BROKER_AUDIENCE": "credential-broker",
        "CB_BROKER_GRANT_DB_PATH": str(tmp_path / "grants.sqlite3"),
        "CB_BROKER_IDEMPOTENCY_DB_PATH": str(tmp_path / "idempotency.sqlite3"),
        "CB_VAULT_BASE_URL": "https://vault.example.test",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CB_BROKER_GRANT_KEK_HEX", raising=False)
    monkeypatch.delenv("CB_VAULT_EMAIL", raising=False)
    monkeypatch.delenv("CB_VAULT_PASSWORD", raising=False)


def test_production_runtime_requires_operator_grant_kek(monkeypatch, tmp_path: Path) -> None:
    _env(monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="CB_BROKER_GRANT_KEK_HEX"):
        build_broker_api(
            browser_factory=_Browser,
            vault_transport=lambda *_args, **_kwargs: (500, b""),
        )


def test_production_runtime_rejects_deployment_wide_vault_password(monkeypatch, tmp_path: Path) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("CB_VAULT_EMAIL", "deployment@example.test")
    monkeypatch.setenv("CB_VAULT_PASSWORD", "deployment-password")
    with pytest.raises(SystemExit, match="CB_BROKER_GRANT_KEK_HEX"):
        build_broker_api(
            browser_factory=_Browser,
            vault_transport=lambda *_args, **_kwargs: (500, b""),
        )
