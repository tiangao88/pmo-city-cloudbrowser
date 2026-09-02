"""Step-14 viewer-to-browser bridge contract."""

from __future__ import annotations

import pytest

from cloudbrowser.browser_slots import BrowserReadiness, BrowserUnavailable
from cloudbrowser.viewer import AuthenticatedViewer, ViewerRequest, ViewerSessionStore
from cloudbrowser.viewer.bridge import BrowserStream, ViewerBrowserBridge


def _session() -> tuple[AuthenticatedViewer, ViewerRequest, object]:
    store = ViewerSessionStore(clock=lambda: 100.0)
    viewer = AuthenticatedViewer(store, token_secret=b"test-secret-012345")
    request = ViewerRequest("req-1", "profile-1", "owner@example.test", "browser-1", "gen-1")
    return viewer, request, viewer.open_session(request)


def test_bridge_returns_owner_bound_stream_only_when_browser_is_ready() -> None:
    _viewer, request, session = _session()
    bridge = ViewerBrowserBridge(
        readiness=lambda: BrowserReadiness("owner@example.test", "gen-1", True),
        stream_endpoint="/internal/browser-stream",
    )
    stream = bridge.open_stream(session, request)
    assert isinstance(stream, BrowserStream)
    assert stream.public_dict() == {
        "profile_id": "profile-1",
        "principal_id": "owner@example.test",
        "browser_id": "browser-1",
        "generation": "gen-1",
        "endpoint": "/internal/browser-stream",
    }
    assert session.token not in stream.public_dict().values()


def test_bridge_rejects_wrong_readiness_owner_or_generation() -> None:
    _viewer, request, session = _session()
    for readiness in (
        BrowserReadiness("other@example.test", "gen-1", True),
        BrowserReadiness("owner@example.test", "gen-2", True),
    ):
        bridge = ViewerBrowserBridge(readiness=lambda readiness=readiness: readiness, stream_endpoint="/stream")
        with pytest.raises(PermissionError):
            bridge.open_stream(session, request)


def test_bridge_rejects_unready_browser() -> None:
    _viewer, request, session = _session()
    bridge = ViewerBrowserBridge(
        readiness=lambda: BrowserReadiness("owner@example.test", "gen-1", False),
        stream_endpoint="/stream",
    )
    with pytest.raises(BrowserUnavailable, match="browser is not ready"):
        bridge.open_stream(session, request)


def test_bridge_does_not_accept_external_stream_urls() -> None:
    with pytest.raises(ValueError):
        ViewerBrowserBridge(readiness=lambda: BrowserReadiness("owner", "gen", True), stream_endpoint="https://evil.test")
