"""Runtime composition tests for the downloads service."""

from __future__ import annotations

import pytest

import cloudbrowser.service_runtime as service_runtime


def _set_runtime_env(monkeypatch, *, secret: str | None = "secret-value") -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "test-downloads")
    monkeypatch.setenv("CB_RELEASE_VERSION", "0.2.0-dev1")
    monkeypatch.setenv("CB_PORT", "8093")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "owner@example.test")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-7")
    monkeypatch.setenv("CB_BINDING_GENERATION", "generation-9")
    monkeypatch.setenv("CB_DOWNLOADS_SHARED_SECRET", "secret-value")
    if secret is None:
        monkeypatch.delenv("CB_DOWNLOADS_SHARED_SECRET", raising=False)


def test_service_runtime_downloads_uses_server_owned_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    def fake_create_server(service, *, server_identity, trusted_secret, address):
        captured["service"] = service
        captured["server_identity"] = server_identity
        captured["trusted_secret"] = trusted_secret
        captured["address"] = address
        return FakeServer()

    monkeypatch.setattr(
        "cloudbrowser.downloads.api.create_downloads_server",
        fake_create_server,
    )
    _set_runtime_env(monkeypatch)

    service_runtime.run_service("downloads")

    identity = captured["server_identity"]
    assert identity.component == "downloads"
    assert identity.instance_id == "test-downloads"
    assert captured["trusted_secret"] == b"secret-value"
    assert captured["address"] == ("0.0.0.0", 8093)
    assert captured["served"] is True
    assert captured["closed"] is True


def test_service_runtime_downloads_requires_shared_secret(monkeypatch) -> None:
    _set_runtime_env(monkeypatch, secret=None)
    with pytest.raises(SystemExit, match="CB_DOWNLOADS_SHARED_SECRET"):
        service_runtime.run_service("downloads")
