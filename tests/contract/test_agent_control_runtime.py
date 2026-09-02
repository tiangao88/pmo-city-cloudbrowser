"""Contract tests for wiring the restricted agent-control service."""

from __future__ import annotations

import pytest

from cloudbrowser.agent_control import AgentControlService


def _set_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "test-agent-control")
    monkeypatch.setenv("CB_RELEASE_VERSION", "0.2.0-dev1")
    monkeypatch.setenv("CB_PORT", "8091")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "owner@example.test")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-7")
    monkeypatch.setenv("CB_BINDING_GENERATION", "generation-9")
    monkeypatch.setenv("CB_AGENT_CONTROL_SHARED_SECRET", "test-secret")


def test_service_runtime_agent_control_uses_server_binding(monkeypatch) -> None:
    """The service branch must construct agent control from env-bound identity."""
    import cloudbrowser.service_runtime as runtime

    captured: dict[str, object] = {}

    class FakeServer:
        def serve_forever(self):
            captured["served"] = True

        def server_close(self):
            captured["closed"] = True

    def fake_create_server(browser, **kwargs):
        captured["browser"] = browser
        captured.update(kwargs)
        return FakeServer()

    monkeypatch.setattr(AgentControlService, "create_server", staticmethod(fake_create_server))
    _set_runtime_env(monkeypatch)

    runtime.run_service("agent-control")

    assert captured["principal_id"] == "owner@example.test"
    assert captured["browser_id"] == "browser-7"
    assert captured["generation"] == "generation-9"
    assert captured["shared_secret"] == "test-secret"
    assert captured["served"] is True
    assert captured["closed"] is True


def test_agent_control_runtime_does_not_fall_back_to_generic_health(monkeypatch) -> None:
    import cloudbrowser.service_runtime as runtime

    _set_runtime_env(monkeypatch)
    called = {"health": False}
    monkeypatch.setattr(runtime, "serve_health", lambda **kwargs: called.update(health=True))
    monkeypatch.setattr(
        AgentControlService,
        "create_server",
        staticmethod(
            lambda *args, **kwargs: type(
                "Server",
                (),
                {"serve_forever": lambda self: None, "server_close": lambda self: None},
            )()
        ),
    )

    runtime.run_service("agent-control")
    assert called["health"] is False


def test_agent_control_runtime_requires_shared_secret(monkeypatch) -> None:
    import cloudbrowser.service_runtime as runtime

    _set_runtime_env(monkeypatch)
    monkeypatch.delenv("CB_AGENT_CONTROL_SHARED_SECRET")

    with pytest.raises(SystemExit, match="CB_AGENT_CONTROL_SHARED_SECRET is required"):
        runtime.run_service("agent-control")


@pytest.mark.parametrize("missing", ["CB_PRINCIPAL_ID", "CB_BROWSER_ID", "CB_BINDING_GENERATION"])
def test_agent_control_runtime_requires_complete_binding(monkeypatch, missing: str) -> None:
    import cloudbrowser.service_runtime as runtime

    _set_runtime_env(monkeypatch)
    monkeypatch.delenv(missing)

    with pytest.raises(SystemExit, match=f"{missing} is required"):
        runtime.run_service("agent-control")
