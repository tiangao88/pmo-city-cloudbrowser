from dataclasses import replace
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer import AuthenticatedViewer, ViewerRequest, ViewerSessionStore
from cloudbrowser.viewer.slot_authority import SlotViewerAuthority

HEADERS = {"Remote-Sub": "alice-sub", "Remote-Groups": "PMOC_Users"}


def setup():
    binding = ViewerRequest("r", "p", "alice", "b", "g1")
    state = {"binding": binding}
    identity = SimpleNamespace(resolve=lambda i: {"alice-sub": "alice", "bob-sub": "bob"}.get(i.sub))
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 0), token_secret=b"synthetic-secret-only")
    authority = SlotViewerAuthority(viewer=viewer, identity_client=identity,
        readiness=lambda: BrowserReadiness(state["binding"].principal_id, state["binding"].generation, True),
        stream_endpoint="/websockify")
    authority.rebind(binding, apply_binding=lambda: None)
    return authority, state, identity


def connect(authority, send=lambda frame: None, close=lambda: None):
    session = authority.issue(trusted_headers=HEADERS)
    return session, authority.connect(trusted_headers=HEADERS, token=session.token,
        send_frame=send, close_transport=close)


@pytest.mark.parametrize("headers", [
    {}, {"Remote-Email": "alice@example.test", "Remote-Groups": "PMOC_Users"},
    {"Remote-Sub": "bob-sub", "Remote-Groups": "PMOC_Users"},
    {"Remote-Sub": "alice-sub"},
])
def test_only_resolved_current_owner_can_issue(headers):
    authority, _, _ = setup()
    with pytest.raises(PermissionError):
        authority.issue(trusted_headers=headers)


def test_identity_service_failure_denies_admission():
    authority, _, identity = setup()
    identity.resolve = lambda _: (_ for _ in ()).throw(RuntimeError("private detail"))
    with pytest.raises(PermissionError, match="^viewer unavailable$"):
        authority.issue(trusted_headers=HEADERS)


def test_rebind_closes_before_mutation_and_old_token_stays_invalid():
    authority, state, _ = setup()
    events = []
    session, connection = connect(authority, send=lambda _: events.append("frame"), close=lambda: events.append("close"))
    new = replace(state["binding"], generation="g2")
    def apply():
        events.append("apply")
        state["binding"] = new
    authority.rebind(new, apply_binding=apply)
    assert events == ["close", "apply"]
    assert not connection.forward_frame(b"stale")
    with pytest.raises(PermissionError):
        authority.connect(trusted_headers=HEADERS, token=session.token, send_frame=lambda _: None, close_transport=lambda: None)
    with pytest.raises(ValueError):
        authority.rebind(replace(new, generation="g1"), apply_binding=lambda: None)
    _, fresh = connect(authority)
    assert fresh.forward_frame(b"new")


def test_rebind_waits_for_inflight_frame():
    authority, state, _ = setup()
    entered, release, requested, applied = Event(), Event(), Event(), Event()
    def send(_):
        entered.set()
        assert release.wait(2)
    _, connection = connect(authority, send=send)
    writer = Thread(target=lambda: connection.forward_frame(b"frame"))
    def transition():
        requested.set()
        authority.rebind(replace(state["binding"], generation="g2"), apply_binding=applied.set)
    switch = Thread(target=transition)
    writer.start()
    try:
        assert entered.wait(2)
        switch.start()
        assert requested.wait(2)
        assert not applied.wait(0.05)
    finally:
        release.set()
        writer.join(2)
        if switch.ident is not None:
            switch.join(2)
    assert applied.is_set()
    assert not connection.forward_frame(b"stale")


def test_failed_close_blocks_mutation_and_future_rebind():
    authority, state, _ = setup()
    connect(authority, close=lambda: (_ for _ in ()).throw(OSError("close failed")))
    applied = []
    for generation in ("g2", "g3"):
        with pytest.raises(RuntimeError):
            authority.rebind(replace(state["binding"], generation=generation), apply_binding=lambda: applied.append(True))
    assert not applied
    with pytest.raises(PermissionError):
        authority.issue(trusted_headers=HEADERS)


def test_leave_disables_admission_and_closes_existing_view():
    authority, _, _ = setup()
    _, connection = connect(authority)
    authority.rebind(None, apply_binding=lambda: None)
    assert connection.closed
    with pytest.raises(PermissionError):
        authority.issue(trusted_headers=HEADERS)


def test_failed_apply_leaves_admission_disabled():
    authority, state, _ = setup()
    _, connection = connect(authority)
    def fail():
        raise RuntimeError("synthetic apply failure")
    with pytest.raises(RuntimeError):
        authority.rebind(replace(state["binding"], generation="g2"), apply_binding=fail)
    assert connection.closed
    with pytest.raises(PermissionError):
        authority.issue(trusted_headers=HEADERS)


def test_close_failure_outside_rebind_also_blocks_future_transition():
    authority, state, _ = setup()
    _, connection = connect(authority, close=lambda: (_ for _ in ()).throw(OSError("failed")))
    with pytest.raises(OSError):
        connection.revoke()
    with pytest.raises(RuntimeError):
        authority.rebind(replace(state["binding"], generation="g2"), apply_binding=lambda: None)
