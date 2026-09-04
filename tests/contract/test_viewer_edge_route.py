"""Viewer public-root and shared edge-identity route tests."""

from __future__ import annotations

import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path

import pytest

from cloudbrowser.identity_link_service import IdentityLinkStore, create_identity_link_server
from cloudbrowser.identity_links import IdentityLinkClient
from cloudbrowser.viewer import (
    AuthenticatedViewer,
    ViewerRequest,
    ViewerSessionStore,
    create_viewer_server,
)

_SECRET = "identity-link-test-secret-012345"
_ISSUER = "https://auth.example.test"
_REALM = "tinyauth.example.test"


def _start_server(tmp_path: Path, *, allow_edge_identity: bool = False):
    identity_store = IdentityLinkStore(tmp_path / "identity.sqlite3")
    identity_server = create_identity_link_server(
        identity_store,
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
        address=("127.0.0.1", 0),
    )
    identity_thread = threading.Thread(target=identity_server.serve_forever, daemon=True)
    identity_thread.start()
    identity_client = IdentityLinkClient(
        base_url=f"http://127.0.0.1:{identity_server.server_address[1]}",
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
    )
    store = ViewerSessionStore(clock=lambda: 100.0)
    viewer = AuthenticatedViewer(
        store, token_secret=b"test-secret-012345", identity_client=identity_client
    )
    request = ViewerRequest("req-1", "profile-1", "pmo-owner-001", "browser-1", "gen-1")
    session = viewer.open_session(request)
    server = create_viewer_server(
        viewer, address=("127.0.0.1", 0), allow_edge_identity=allow_edge_identity
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, session, identity_server, identity_thread, f"http://{host}:{port}"


def _teardown(server, thread, identity_server, identity_thread) -> None:
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()
    identity_server.shutdown()
    identity_thread.join(timeout=3)
    identity_server.server_close()


def _assert_http_error(code: int, call) -> None:
    with pytest.raises(HTTPError) as exc:
        call()
    assert exc.value.code == code


def test_root_serves_shell_for_resolved_edge_identity(tmp_path: Path) -> None:
    server, thread, _session, identity_server, identity_thread, base = _start_server(
        tmp_path, allow_edge_identity=True
    )
    try:
        response = urlopen(
            Request(
                base + "/",
                headers={
                    "Remote-Sub": "oidc-sub-1",
                    "Remote-Email": "owner@example.com",
                    "Remote-Groups": "PMOC_Users",
                },
            )
        )
        assert response.status == 200
        assert response.headers.get_content_type() == "text/html"
        assert response.headers.get("Cache-Control") == "no-store"
        body = response.read().decode()
        assert "CloudBrowser" in body
        assert "owner@example.com" not in body
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_viewer_path_accepts_local_remote_user_without_bearer(tmp_path: Path) -> None:
    server, thread, _session, identity_server, identity_thread, base = _start_server(
        tmp_path, allow_edge_identity=True
    )
    try:
        response = urlopen(
            Request(
                base + "/viewer",
                headers={
                    "Remote-User": "local-owner",
                    "Remote-Email": "pseudo@example.com",
                    "Remote-Groups": "PMOC_Users",
                },
            )
        )
        assert response.status == 200
        assert "CloudBrowser" in response.read().decode()
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_email_or_unauthorized_group_identity_fails_closed(tmp_path: Path) -> None:
    server, thread, _session, identity_server, identity_thread, base = _start_server(
        tmp_path, allow_edge_identity=True
    )
    try:
        _assert_http_error(
            401,
            lambda: urlopen(Request(base + "/", headers={"Remote-Email": "owner@example.com"})),
        )
        _assert_http_error(
            401,
            lambda: urlopen(
                Request(
                    base + "/",
                    headers={
                        "Remote-Email": "owner@example.com",
                        "Remote-User": "owner",
                        "Remote-Groups": "Other",
                    },
                )
            ),
        )
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_root_without_identity_or_token_fails_closed(tmp_path: Path) -> None:
    server, thread, _session, identity_server, identity_thread, base = _start_server(
        tmp_path, allow_edge_identity=True
    )
    try:
        _assert_http_error(401, lambda: urlopen(Request(base + "/")))
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_edge_identity_disabled_keeps_bearer_only_behavior(tmp_path: Path) -> None:
    server, thread, _session, identity_server, identity_thread, base = _start_server(
        tmp_path, allow_edge_identity=False
    )
    try:
        _assert_http_error(
            401,
            lambda: urlopen(
                Request(
                    base + "/",
                    headers={"Remote-Sub": "oidc-sub-1", "Remote-Groups": "PMOC_Users"},
                )
            ),
        )
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_bearer_token_still_authorizes_when_edge_identity_enabled(tmp_path: Path) -> None:
    server, thread, session, identity_server, identity_thread, base = _start_server(
        tmp_path, allow_edge_identity=True
    )
    try:
        response = urlopen(
            Request(base + "/viewer", headers={"Authorization": f"Bearer {session.token}"})
        )
        assert response.status == 200
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_health_is_public_and_unknown_routes_are_not(tmp_path: Path) -> None:
    server, thread, _session, identity_server, identity_thread, base = _start_server(tmp_path)
    try:
        response = urlopen(Request(base + "/health"))
        assert response.status == 200
        _assert_http_error(404, lambda: urlopen(Request(base + "/raw-cdp")))
    finally:
        _teardown(server, thread, identity_server, identity_thread)


def test_allow_edge_identity_requires_boolean(tmp_path: Path) -> None:
    identity_store = IdentityLinkStore(tmp_path / "identity.sqlite3")
    identity_server = create_identity_link_server(
        identity_store,
        shared_secret=_SECRET,
        oidc_issuer=_ISSUER,
        tinyauth_realm=_REALM,
        address=("127.0.0.1", 0),
    )
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 100.0), token_secret=b"test-secret-012345")
    with pytest.raises(TypeError):
        create_viewer_server(viewer, address=("127.0.0.1", 0), allow_edge_identity="yes")  # type: ignore[arg-type]
    identity_server.server_close()
