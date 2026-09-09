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
def test_credential_broker_compose_wires_browser_and_required_secrets(filename: str) -> None:
    block = _block(filename, "credential-broker:", "networks:")
    for marker in (
        "CB_BROWSER_API_URL: http://browser:9230",
        "CB_BROKER_SHARED_SECRET:",
        "CB_BROKER_SUBMIT_SECRET:",
        "CB_BROKER_ADAPTER:",
        "CB_BROKER_SITE_ID:",
        "CB_BROKER_ORIGIN:",
        "CB_VAULT_BASE_URL:",
        "CB_VAULT_EMAIL:",
        "CB_VAULT_PASSWORD:",
    ):
        assert marker in block
    assert "browser:" in block


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
