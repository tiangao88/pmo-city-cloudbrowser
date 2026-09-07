"""Viewer runtime wires the session surface to the router control plane.

When the authenticated edge mode is enabled the viewer runtime must build
a ``ViewerSessionSurface`` backed by a bounded HTTP client to the router
(``CB_ROUTER_BASE_URL``) and hand it to ``create_viewer_server``. Without
a router URL (or outside edge mode) the viewer keeps its bearer-only
behavior with no surface routes.
"""

from __future__ import annotations

import cloudbrowser.service_runtime as service_runtime


class _FakeNamespace:
    def __init__(self, instance_id: str) -> None:
        pass


class _FakeStore:
    def __init__(self, *, clock) -> None:
        pass


class _FakeViewer:
    def __init__(self, store, *, token_secret: bytes, ttl_s: float, identity_client) -> None:
        pass


class _FakeServer:
    def __init__(self) -> None:
        self.captured: dict[str, object] = {}

    def serve_forever(self) -> None:
        self.captured["served"] = True

    def server_close(self) -> None:
        self.captured["closed"] = True


class _FakeSurface:
    def __init__(self, *, identity_client, router_api) -> None:
        self.identity_client = identity_client
        self.router_api = router_api


class _FakeRouterClient:
    def __init__(self, *, base_url: str) -> None:
        self.base_url = base_url


def _setup(
    monkeypatch, *, edge: bool = True, router_url: str = "http://router:8080"
) -> dict[str, object]:
    captured: dict[str, object] = {}

    monkeypatch.setattr(service_runtime, "InstanceNamespace", _FakeNamespace)
    monkeypatch.setenv("CB_INSTANCE_ID", "test-instance")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test-release")
    monkeypatch.setenv("CB_PORT", "8082")
    monkeypatch.setenv("CB_VIEWER_TOKEN_SECRET", "viewer-secret-value")
    if edge:
        monkeypatch.setenv("CB_EDGE_AUTH", "traefik-forwardauth")
        monkeypatch.setenv("CB_IDENTITY_LINK_BASE_URL", "http://identity-link:8091")
        monkeypatch.setenv("CB_IDENTITY_LINK_SHARED_SECRET", "identity-link-secret-16")
        monkeypatch.setenv("CB_OIDC_ISSUER", "https://auth.example.test")
        monkeypatch.setenv("CB_TINYAUTH_REALM", "tinyauth.example.test")
        monkeypatch.setenv("CB_ROUTER_BASE_URL", router_url)
    else:
        monkeypatch.delenv("CB_EDGE_AUTH", raising=False)
        monkeypatch.delenv("CB_ROUTER_BASE_URL", raising=False)
    monkeypatch.setattr("cloudbrowser.viewer.ViewerSessionStore", _FakeStore)
    monkeypatch.setattr("cloudbrowser.viewer.AuthenticatedViewer", _FakeViewer)
    monkeypatch.setattr("cloudbrowser.identity_links.build_identity_link_client", lambda: object())
    monkeypatch.setattr("cloudbrowser.viewer.session_surface.ViewerSessionSurface", _FakeSurface)
    monkeypatch.setattr(
        "cloudbrowser.viewer.session_surface.RouterHttpClient",
        lambda *, base_url: _FakeRouterClient(base_url=base_url),
    )

    def _fake_create(viewer, *, address, allow_edge_identity=False, session_surface=None):
        captured["allow_edge_identity"] = allow_edge_identity
        captured["surface"] = session_surface
        return _FakeServer()

    monkeypatch.setattr("cloudbrowser.viewer.create_viewer_server", _fake_create)
    return captured


def test_edge_mode_builds_surface_with_router_client(monkeypatch) -> None:
    captured = _setup(monkeypatch)
    service_runtime.run_service("viewer")
    surface = captured["surface"]
    assert isinstance(surface, _FakeSurface)
    router_client = surface.router_api
    assert isinstance(router_client, _FakeRouterClient)
    assert router_client.base_url == "http://router:8080"
    assert captured["allow_edge_identity"] is True


def test_no_edge_mode_keeps_bearer_only_without_surface(monkeypatch) -> None:
    captured = _setup(monkeypatch, edge=False)
    service_runtime.run_service("viewer")
    assert captured["surface"] is None
    assert captured["allow_edge_identity"] is False


def test_edge_mode_without_router_url_refuses_to_boot(monkeypatch) -> None:
    _setup(monkeypatch)
    import os

    os.environ.pop("CB_ROUTER_BASE_URL")
    try:
        service_runtime.run_service("viewer")
    except SystemExit as exc:
        assert "CB_ROUTER_BASE_URL" in str(exc)
    else:
        raise AssertionError("viewer must fail closed without CB_ROUTER_BASE_URL")
