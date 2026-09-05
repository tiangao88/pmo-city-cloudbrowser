"""Step-15 viewer seam: bridge integration with owner-bound, server-derived bindings.

The seam pins ``ViewerBrowserBridge`` to the router-derived ``BrowserBinding``
of the slot browser this viewer serves instead of trusting a caller-supplied
token/binding: readiness is consulted through the narrow browser transport
before any stream is opened, the stream tuple fields match the server binding
exactly, and mismatches fail closed without leaking secrets or raw transport
details.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.browser_slots import BrowserBinding, BrowserReadiness, BrowserUnavailable
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.router.sessions import RouterSession, RouterSessionStore, SessionStatus, SlotDescriptor
from cloudbrowser.viewer import AuthenticatedViewer, ViewerRequest, ViewerSession, ViewerSessionStore
from cloudbrowser.viewer.bridge import BrowserStream, ViewerBrowserBridge


class _BrowserReadinessClient:
    """HttpClient-protocol stub serving one mutable /browser/readiness answer."""

    def __init__(self, readiness: BrowserReadiness) -> None:
        self.readiness_calls = 0
        self._readiness = readiness

    def request(self, method: str, path: str, *, body: str | None = None) -> object:
        if (method, path) != ("GET", "/browser/readiness"):
            raise AssertionError(f"unexpected browser API call: {method} {path}")
        self.readiness_calls += 1
        return {
            "owner": self._readiness.owner,
            "generation": self._readiness.generation,
            "cdp_ok": self._readiness.cdp_ok,
        }


def _router_session(tmp_path: Path, *, name: str, browser_id: str) -> RouterSession:
    """Derive an ACTIVE router session with a binding exactly as the router does."""
    store = RouterSessionStore(
        tmp_path / f"{name}-state.json",
        slots=[SlotDescriptor(slot_id=f"slot-{name}", supervisor_url="http://127.0.0.1:1", browser_id=browser_id)],
        clock=lambda: 100.0,
    )
    store.enqueue("principal-owner", request_id="req-1")
    record = store.for_principal("principal-owner")
    assert record is not None and record.binding is not None
    assert record.status is SessionStatus.OFFERED
    return store.activate(record.session_id)


def _viewer_request(binding: BrowserBinding) -> ViewerRequest:
    return ViewerRequest("req-1", binding.profile_id, binding.principal_id, binding.browser_id, binding.generation)


def _open_viewer_session(binding: BrowserBinding) -> tuple[AuthenticatedViewer, ViewerSession]:
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 100.0), token_secret=b"test-secret-012345")
    return viewer, viewer.open_session(_viewer_request(binding))


def test_bridge_opens_stream_matching_server_derived_binding_after_readiness(tmp_path: Path) -> None:
    record = _router_session(tmp_path, name="slot-a", browser_id="browser-1")
    binding = record.binding
    assert binding is not None
    _viewer, session = _open_viewer_session(binding)

    client = _BrowserReadinessClient(BrowserReadiness(binding.principal_id, binding.generation, True))
    transport = HttpBrowserTransport(
        client, expected_owner=binding.principal_id, expected_generation=binding.generation
    )
    bridge = ViewerBrowserBridge(
        binding=binding, readiness=transport.readiness, stream_endpoint="/internal/browser-stream"
    )

    stream = bridge.open_stream(session, _viewer_request(binding))

    assert isinstance(stream, BrowserStream)
    assert client.readiness_calls >= 1  # readiness is consulted before the stream opens
    public = stream.public_dict()
    assert set(public) == {"profile_id", "principal_id", "browser_id", "generation", "endpoint"}
    assert (public["profile_id"], public["principal_id"], public["browser_id"], public["generation"]) == (
        binding.profile_id,
        binding.principal_id,
        binding.browser_id,
        binding.generation,
    )
    assert session.token not in public.values()
    assert "BrowserStream" in repr(stream)


def test_bridge_denies_consistent_session_bound_to_a_different_browser(tmp_path: Path) -> None:
    server_record = _router_session(tmp_path, name="slot-b", browser_id="browser-2")
    server_binding = server_record.binding
    assert server_binding is not None
    other_record = _router_session(tmp_path, name="slot-a", browser_id="browser-1")
    other_binding = other_record.binding
    assert other_binding is not None

    # Caller session, request, and readiness are mutually consistent for browser-1;
    # the viewer bridge is server-bound to browser-2, so this must fail closed.
    _viewer, session = _open_viewer_session(other_binding)
    bridge = ViewerBrowserBridge(
        binding=server_binding,
        readiness=lambda: BrowserReadiness(other_binding.principal_id, other_binding.generation, True),
        stream_endpoint="/stream",
    )
    with pytest.raises(PermissionError, match="viewer binding mismatch"):
        bridge.open_stream(session, _viewer_request(other_binding))


def test_bridge_rejects_bound_browser_that_is_not_ready(tmp_path: Path) -> None:
    record = _router_session(tmp_path, name="slot-a", browser_id="browser-1")
    binding = record.binding
    assert binding is not None
    _viewer, session = _open_viewer_session(binding)

    client = _BrowserReadinessClient(BrowserReadiness(binding.principal_id, binding.generation, False))
    transport = HttpBrowserTransport(
        client, expected_owner=binding.principal_id, expected_generation=binding.generation
    )
    bridge = ViewerBrowserBridge(binding=binding, readiness=transport.readiness, stream_endpoint="/stream")

    with pytest.raises(BrowserUnavailable, match="browser is not ready"):
        bridge.open_stream(session, _viewer_request(binding))
    assert client.readiness_calls >= 1
