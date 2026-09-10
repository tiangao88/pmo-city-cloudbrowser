"""Runtime wiring and compose contract for the live credential broker."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser import service_runtime

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/coolify"


def _block(filename: str, start: str, end: str) -> str:
    text = (COMPOSE / filename).read_text(encoding="utf-8")
    return text.split(f"  {start}\n", 1)[1].split(f"  {end}\n", 1)[0]


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_credential_broker_compose_wires_browser_and_custody_secrets(filename: str) -> None:
    block = _block(filename, "credential-broker:", "networks:")
    for marker in (
        "CB_BROWSER_API_URL: http://browser:9230",
        "CB_CREDENTIAL_CAPABILITY_SECRET:",
        "CB_BROKER_SUBMIT_SECRET:",
        "CB_BROKER_GRANT_KEK_HEX:",
        "CB_BROKER_ADAPTER:",
        "CB_BROKER_SITE_ID:",
        "CB_BROKER_ORIGIN:",
        "CB_VAULT_BASE_URL:",
    ):
        assert marker in block
    assert "CB_BROKER_SHARED_SECRET:" not in block
    assert "browser:" in block


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_production_compose_excludes_deployment_wide_vault_credentials(filename: str) -> None:
    text = (COMPOSE / filename).read_text(encoding="utf-8")
    for forbidden in ("CB_VAULT_EMAIL", "CB_VAULT_PASSWORD"):
        assert forbidden not in text


def test_production_runtime_has_no_legacy_password_grant_client_reachability() -> None:
    runtime_paths = (
        ROOT / "src/cloudbrowser/credential_broker/runtime.py",
        ROOT / "src/cloudbrowser/service_runtime.py",
        ROOT / "services/credential-broker/entrypoint.py",
        ROOT / "services/credential-broker/Dockerfile",
    )
    for path in runtime_paths:
        text = path.read_text(encoding="utf-8")
        assert "vault_client" not in text
        assert "CB_VAULT_EMAIL" not in text
        assert "CB_VAULT_PASSWORD" not in text
    assert not (ROOT / "src/cloudbrowser/security/vault_client.py").exists()


def test_deployment_env_contract_lists_coolify_and_source_inputs() -> None:
    env_example = (COMPOSE / ".env.example").read_text(encoding="utf-8")
    for required in (
        "SERVICE_PASSWORD_64_ROUTERSECRET",
        "SERVICE_PASSWORD_64_CREDENTIALCAPSECRET",
        "SERVICE_PASSWORD_64_BROKERSUBMIT",
        "CB_CREDENTIAL_CAPABILITY_SECRET",
        "CB_BROKER_GRANT_KEK_HEX",
        "CB_VAULT_BASE_URL",
        "CB_BROKER_SITE_ID",
        "CB_BROKER_ORIGIN",
        "CB_BROKER_SUCCESS_PATH",
    ):
        assert required in env_example
    assert "CB_BROKER_GRANT_DB_PATH" in env_example or "grant-custody-v1.sqlite3" in env_example
    for forbidden in ("CB_VAULT_EMAIL", "CB_VAULT_PASSWORD"):
        assert forbidden not in env_example


def test_coolify_compose_requires_non_magic_custody_inputs() -> None:
    compose = (COMPOSE / "compose.coolify.yaml").read_text(encoding="utf-8")
    assert "CB_CREDENTIAL_CAPABILITY_SECRET: ${SERVICE_PASSWORD_64_CREDENTIALCAPSECRET:?SERVICE_PASSWORD_64_CREDENTIALCAPSECRET is required}" in compose
    assert "CB_BROKER_GRANT_KEK_HEX: ${CB_BROKER_GRANT_KEK_HEX:?CB_BROKER_GRANT_KEK_HEX is required}" in compose
    assert "CB_VAULT_BASE_URL: ${CB_VAULT_BASE_URL:?CB_VAULT_BASE_URL is required}" in compose


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_browser_compose_receives_only_one_way_broker_submit_secret(filename: str) -> None:
    block = _block(filename, "browser:", "agent-control:")
    assert "CB_BROKER_SUBMIT_SECRET:" in block
    assert "CB_BROKER_SHARED_SECRET:" not in block
    assert "CB_VAULT_PASSWORD" not in block
    assert "CB_VAULT_EMAIL" not in block


def test_service_runtime_runs_real_broker_server(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    monkeypatch.setenv("CB_INSTANCE_ID", "test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test")
    monkeypatch.setenv("CB_PORT", "8084")
    import cloudbrowser.credential_broker.runtime as runtime

    monkeypatch.setattr(
        runtime,
        "create_broker_server",
        lambda address: (captured.update(address=address) or FakeServer()),
    )
    monkeypatch.setattr(
        service_runtime,
        "serve_health",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("health-only fallback used")),
    )

    service_runtime.run_service("credential-broker")

    assert captured == {
        "address": ("0.0.0.0", 8084),
        "served": True,
        "closed": True,
    }
