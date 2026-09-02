"""Step-14 viewer contract: owner-bound, authenticated, browser-only sessions."""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.viewer import (
    AuthenticatedViewer,
    ViewerRequest,
    ViewerSession,
    ViewerSessionStore,
    create_viewer_server,
)


def test_session_issues_bounded_owner_bound_token_and_public_metadata() -> None:
    store = ViewerSessionStore(clock=lambda: 100.0)
    viewer = AuthenticatedViewer(store, token_secret=b"test-secret-012345")
    session = viewer.open_session(
        ViewerRequest(
            request_id="req-1",
            profile_id="profile-1",
            principal_id="owner@example.test",
            browser_id="browser-1",
            generation="gen-1",
        )
    )

    assert session.principal_id == "owner@example.test"
    assert session.profile_id == "profile-1"
    assert session.browser_id == "browser-1"
    assert session.expires_at == 460.0
    assert session.public_dict() == {
        "request_id": "req-1",
        "profile_id": "profile-1",
        "principal_id": "owner@example.test",
        "browser_id": "browser-1",
        "generation": "gen-1",
        "expires_at": 460.0,
    }
    assert "test-secret" not in repr(session)


def test_token_is_required_and_cannot_be_replayed_for_another_binding() -> None:
    store = ViewerSessionStore(clock=lambda: 100.0)
    viewer = AuthenticatedViewer(store, token_secret=b"test-secret-012345")
    request = ViewerRequest("req-1", "profile-1", "owner@example.test", "browser-1", "gen-1")
    session = viewer.open_session(request)

    assert viewer.authorize(session.token, request) == session
    with pytest.raises(PermissionError, match="viewer binding mismatch"):
        viewer.authorize(
            session.token,
            ViewerRequest("req-2", "profile-2", "other@example.test", "browser-2", "gen-2"),
        )
    with pytest.raises(PermissionError, match="viewer token required"):
        viewer.authorize("", request)


def test_expired_or_revoked_session_fails_closed() -> None:
    now = [100.0]
    store = ViewerSessionStore(clock=lambda: now[0])
    viewer = AuthenticatedViewer(store, token_secret=b"test-secret-012345", ttl_s=60.0)
    request = ViewerRequest("req-1", "profile-1", "owner@example.test", "browser-1", "gen-1")
    session = viewer.open_session(request)
    store.revoke(session.token)
    with pytest.raises(PermissionError, match="viewer session unavailable"):
        viewer.authorize(session.token, request)

    session = viewer.open_session(request)
    now[0] = 160.0
    with pytest.raises(PermissionError, match="viewer session unavailable"):
        viewer.authorize(session.token, request)


def test_viewer_server_serves_authenticated_shell_only_and_denies_raw_cdp() -> None:
    store = ViewerSessionStore(clock=lambda: 100.0)
    viewer = AuthenticatedViewer(store, token_secret=b"test-secret-012345")
    request = ViewerRequest("req-1", "profile-1", "owner@example.test", "browser-1", "gen-1")
    session = viewer.open_session(request)
    server = create_viewer_server(viewer, address=("127.0.0.1", 0))
    try:
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        base = f"http://{host}:{port}"

        response = urlopen(Request(base + "/viewer", headers={"Authorization": "Bearer " + session.token}))
        assert response.status == 200
        assert response.headers.get_content_type() == "text/html"
        body = response.read().decode()
        assert "CloudBrowser" in body
        assert session.token not in body
        assert "owner@example.test" not in body

        with pytest.raises(HTTPError) as denied:
            urlopen(Request(base + "/raw-cdp", headers={"Authorization": "Bearer " + session.token}))
        assert denied.value.code == 404

        with pytest.raises(HTTPError) as unauthorized:
            urlopen(Request(base + "/viewer"))
        assert unauthorized.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_viewer_server_rejects_malformed_json_or_caller_identity_override() -> None:
    store = ViewerSessionStore(clock=lambda: 100.0)
    viewer = AuthenticatedViewer(store, token_secret=b"test-secret-012345")
    request = ViewerRequest("req-1", "profile-1", "owner@example.test", "browser-1", "gen-1")
    session = viewer.open_session(request)
    server = create_viewer_server(viewer, address=("127.0.0.1", 0))
    try:
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        payload = json.dumps({
            "token": session.token,
            "request_id": "req-1",
            "profile_id": "profile-2",
            "principal_id": "other@example.test",
            "browser_id": "browser-2",
            "generation": "gen-2",
        }).encode()
        req = Request(
            f"http://{host}:{port}/viewer/session",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(HTTPError) as denied:
            urlopen(req)
        assert denied.value.code == 403
        assert b"other@example.test" not in denied.value.read()
    finally:
        server.shutdown()
        server.server_close()
