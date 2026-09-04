"""Viewer service runtime composition tests."""

from __future__ import annotations

import os

import cloudbrowser.service_runtime as service_runtime


def test_viewer_wiring_uses_token_secret_and_shared_identity_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeNamespace:
        def __init__(self, instance_id: str) -> None:
            captured["instance_id"] = instance_id

    class FakeStore:
        def __init__(self, *, clock) -> None:
            captured["clock"] = clock

    class FakeViewer:
        def __init__(self, store, *, token_secret: bytes, ttl_s: float, identity_client) -> None:
            captured["store"] = store
            captured["secret"] = token_secret
            captured["ttl"] = ttl_s
            captured["identity_client"] = identity_client

    class FakeResolver:
        pass

    class FakeServer:
        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(service_runtime, "InstanceNamespace", FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8082")
    monkeypatch.setenv("CB_VIEWER_TOKEN_SECRET", "viewer-secret-value")
    monkeypatch.setenv("CB_VIEWER_SESSION_TTL_S", "300")
    monkeypatch.setenv("CB_EDGE_AUTH", "traefik-forwardauth")
    monkeypatch.setattr("cloudbrowser.viewer.ViewerSessionStore", FakeStore)
    monkeypatch.setattr("cloudbrowser.viewer.AuthenticatedViewer", FakeViewer)
    monkeypatch.setattr("cloudbrowser.identity_links.build_identity_link_client", lambda: FakeResolver())
    monkeypatch.setattr(
        "cloudbrowser.viewer.create_viewer_server",
        lambda viewer, *, address, allow_edge_identity=False: FakeServer(),
    )

    service_runtime.run_service("viewer")

    assert captured["instance_id"] == "test-instance"
    assert captured["secret"] == b"viewer-secret-value"
    assert captured["ttl"] == 300.0
    assert isinstance(captured["identity_client"], FakeResolver)
    assert captured["served"] is True
    assert captured["closed"] is True
    assert callable(captured["clock"])


def test_viewer_requires_secret_and_does_not_fall_back_to_health(monkeypatch) -> None:
    class FakeNamespace:
        def __init__(self, instance_id: str) -> None:
            pass

    monkeypatch.setattr(service_runtime, "InstanceNamespace", FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8082")
    monkeypatch.delenv("CB_VIEWER_TOKEN_SECRET", raising=False)
    monkeypatch.setattr(service_runtime, "serve_health", lambda **_: (_ for _ in ()).throw(AssertionError("health fallback")))

    try:
        service_runtime.run_service("viewer")
    except SystemExit as exc:
        assert str(exc) == "CB_VIEWER_TOKEN_SECRET is required"
    else:
        raise AssertionError("viewer started without the authentication secret")


def test_viewer_treats_empty_edge_auth_env_as_unset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeNamespace:
        def __init__(self, instance_id: str) -> None:
            pass

    class FakeStore:
        def __init__(self, *, clock) -> None:
            pass

    class FakeViewer:
        def __init__(self, store, *, token_secret: bytes, ttl_s: float, identity_client) -> None:
            captured["identity_client"] = identity_client

    class FakeServer:
        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(service_runtime, "InstanceNamespace", FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8082")
    monkeypatch.setenv("CB_VIEWER_TOKEN_SECRET", "viewer-secret-value")
    monkeypatch.setenv("CB_EDGE_AUTH", "")
    monkeypatch.setattr("cloudbrowser.viewer.ViewerSessionStore", FakeStore)
    monkeypatch.setattr("cloudbrowser.viewer.AuthenticatedViewer", FakeViewer)
    monkeypatch.setattr(
        "cloudbrowser.viewer.create_viewer_server",
        lambda viewer, *, address, allow_edge_identity=False: (captured.update(allow_edge_identity=allow_edge_identity) or FakeServer()),
    )

    service_runtime.run_service("viewer")

    assert captured == {"allow_edge_identity": False, "identity_client": None, "served": True, "closed": True}


def test_viewer_secret_is_not_written_to_environment_snapshot_or_logs() -> None:
    assert "CB_VIEWER_TOKEN_SECRET" not in os.environ or isinstance(os.environ["CB_VIEWER_TOKEN_SECRET"], str)
