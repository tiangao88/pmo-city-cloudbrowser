from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer import AuthenticatedViewer, ViewerRequest, ViewerSessionStore
from cloudbrowser.viewer.slot_authority import SlotViewerAuthority
from cloudbrowser.viewer.transition import ViewerTransition

BINDING = BrowserBinding("p", "alice", "b", "g1")
HEADERS = {"Remote-Sub": "a", "Remote-Groups": "PMOC_Users"}


def setup():
    state = {"ready": True}
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 0), token_secret=b"synthetic-viewer-secret")
    authority = SlotViewerAuthority(viewer=viewer, identity_client=SimpleNamespace(resolve=lambda _: "alice"),
        readiness=lambda: BrowserReadiness("alice", "g1", state["ready"]), stream_endpoint="/stream")
    authority.rebind(ViewerRequest("old", "p", "alice", "b", "g1"), apply_binding=lambda: None)
    return authority, state


def test_same_generation_resume_never_reauthorizes_old_cookie():
    authority, _ = setup()
    old = authority.issue(trusted_headers=HEADERS)
    transition = ViewerTransition(authority, reset_display=lambda: None)
    ticket = transition.fence(BINDING)
    transition.enable(ticket, BINDING)
    with pytest.raises(PermissionError):
        authority.connect(trusted_headers=HEADERS, token=old.token, send_frame=lambda _: None, close_transport=lambda: None)
    assert authority.issue(trusted_headers=HEADERS).request_id != old.request_id


def test_new_coordinator_rejects_pre_restart_ticket():
    authority, _ = setup()
    ticket = ViewerTransition(authority).fence(BINDING)
    restarted = ViewerTransition(authority, reset_display=lambda: None)
    with pytest.raises(PermissionError):
        restarted.enable(ticket, BINDING)


@pytest.mark.parametrize("failure", ["not-ready", "cleanup", "missing-cleanup"])
def test_failed_enable_leaves_admission_disabled(failure):
    authority, state = setup()
    def reset():
        if failure == "cleanup":
            raise RuntimeError("synthetic cleanup failure")
    transition = ViewerTransition(authority, reset_display=None if failure == "missing-cleanup" else reset)
    ticket = transition.fence(BINDING)
    state["ready"] = failure != "not-ready"
    with pytest.raises((PermissionError, RuntimeError)):
        transition.enable(ticket, BINDING)
    with pytest.raises(PermissionError):
        authority.issue(trusted_headers=HEADERS)
