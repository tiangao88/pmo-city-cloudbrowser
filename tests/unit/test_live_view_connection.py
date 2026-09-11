from dataclasses import replace

import pytest

from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer import AuthenticatedViewer, ViewerRequest, ViewerSessionStore
from cloudbrowser.viewer.bridge import ViewerBrowserBridge
from cloudbrowser.viewer.live_connection import LiveViewConnection


def setup_connection():
    state = {"now": 0, "request": ViewerRequest("r", "p", "alice", "b", "g1")}
    store = ViewerSessionStore(clock=lambda: state["now"])
    viewer = AuthenticatedViewer(store, token_secret=b"synthetic-secret-only", ttl_s=10)
    session = viewer.open_session(state["request"])
    state["ready"] = BrowserReadiness("alice", "g1", True)
    sent, closed = [], []
    connection = LiveViewConnection(
        viewer=viewer,
        bridge=ViewerBrowserBridge(readiness=lambda: state["ready"], stream_endpoint="/stream"),
        token=session.token,
        current_request=lambda: state["request"],
        send_frame=sent.append,
        close_transport=lambda: closed.append(True),
    )
    return state, store, session, connection, sent, closed


def test_current_owner_receives_frames_without_exposing_token():
    _, _, session, connection, sent, closed = setup_connection()
    assert connection.forward_frame(b"synthetic-frame")
    assert sent == [b"synthetic-frame"]
    assert not closed
    assert session.token not in repr(connection)


@pytest.mark.parametrize("event", ["expiry", "revoke", "owner", "generation", "not_ready"])
def test_authority_loss_closes_existing_connection_before_next_frame(event):
    state, store, session, connection, sent, closed = setup_connection()
    if event == "expiry":
        state["now"] = 10
    elif event == "revoke":
        store.revoke(session.token)
    elif event == "owner":
        state["request"] = replace(state["request"], principal_id="bob")
    elif event == "generation":
        state["ready"] = BrowserReadiness("alice", "g2", True)
    else:
        state["ready"] = BrowserReadiness("alice", "g1", False)
    assert not connection.forward_frame(b"must-not-send")
    assert sent == []
    assert closed == [True]
    assert connection.closed
    connection.revoke()
    assert closed == [True]


def test_idle_poll_expires_connection_and_old_connection_cannot_resume():
    state, _, _, connection, sent, closed = setup_connection()
    state["now"] = 11
    assert not connection.poll()
    state["now"] = 0
    assert not connection.forward_frame(b"stale")
    assert sent == []
    assert closed == [True]


def test_disconnect_fences_subsequent_frames():
    _, _, _, connection, sent, _ = setup_connection()
    connection.revoke()
    assert not connection.forward_frame(b"stale")
    assert sent == []
