from dataclasses import replace
from threading import Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding, OwnerBoundLifecycle
from cloudbrowser.browser_slots.supervisor import SlotSupervisor
from cloudbrowser.browser_slots.transport import BrowserReadiness, BrowserUnavailable
from cloudbrowser.viewer import AuthenticatedViewer, ViewerRequest, ViewerSessionStore
from cloudbrowser.viewer.slot_authority import SlotViewerAuthority
from cloudbrowser.viewer.fence_control import ViewerFenceClient, create_fence_server

SECRET = "synthetic-fence-secret-32-characters"
BINDING = BrowserBinding("p", "alice", "b", "g1")
HEADERS = {"Remote-Sub": "a", "Remote-Groups": "PMOC_Users"}


@pytest.fixture
def rig():
    events = []
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 0), token_secret=b"synthetic-viewer-secret")
    authority = SlotViewerAuthority(viewer=viewer,
        identity_client=SimpleNamespace(resolve=lambda _: "alice"),
        readiness=lambda: BrowserReadiness("alice", "g1", True), stream_endpoint="/stream")
    authority.rebind(ViewerRequest("r", "p", "alice", "b", "g1"), apply_binding=lambda: None)
    session = authority.issue(trusted_headers=HEADERS)
    live = authority.connect(trusted_headers=HEADERS, token=session.token,
        send_frame=lambda _: events.append("frame"), close_transport=lambda: events.append("close"))
    server = create_fence_server(authority, shared_secret=SECRET)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield authority, live, events, url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_supervisor_waits_for_http_fence_before_stopping_and_pushing(rig, tmp_path):
    authority, live, events, url = rig
    lifecycle = OwnerBoundLifecycle(BINDING, tmp_path / "tabs.json")
    lifecycle.start(BINDING)
    lifecycle.mark_ready(BINDING)
    browser = SimpleNamespace(stop=lambda: events.append("stop"), push_binding=lambda _: events.append("push"))
    supervisor = SlotSupervisor(lifecycle, browser,
        viewer_fence=ViewerFenceClient(base_url=url, shared_secret=SECRET))
    supervisor.adopt_binding(replace(BINDING, principal_id="bob", generation="g2"))
    assert events == ["close", "stop", "push"]
    assert not live.forward_frame(b"stale")
    with pytest.raises(PermissionError):
        authority.issue(trusted_headers=HEADERS)


def test_bad_service_auth_prevents_browser_mutation(rig, tmp_path):
    _, live, events, url = rig
    lifecycle = OwnerBoundLifecycle(BINDING, tmp_path / "tabs.json")
    browser = SimpleNamespace(push_binding=lambda _: events.append("push"))
    supervisor = SlotSupervisor(lifecycle, browser,
        viewer_fence=ViewerFenceClient(base_url=url, shared_secret="x" * 32))
    with pytest.raises(BrowserUnavailable):
        supervisor.adopt_binding(replace(BINDING, generation="g2"))
    assert events == []
    assert not live.closed
    assert lifecycle.binding == BINDING


def test_retry_is_safe_but_old_binding_cannot_fence_new_owner(rig):
    authority, live, _, url = rig
    client = ViewerFenceClient(base_url=url, shared_secret=SECRET)
    client(BINDING)
    client(BINDING)
    assert live.closed
    authority.rebind(ViewerRequest("r2", "p", "bob", "b", "g2"), apply_binding=lambda: None)
    with pytest.raises(BrowserUnavailable):
        client(BINDING)


def test_unacknowledged_fence_leaves_lifecycle_unchanged(tmp_path):
    events = []
    lifecycle = OwnerBoundLifecycle(BINDING, tmp_path / "tabs.json")
    def fail(_):
        raise BrowserUnavailable("synthetic timeout")
    supervisor = SlotSupervisor(lifecycle, SimpleNamespace(push_binding=lambda _: events.append("push")), viewer_fence=fail)
    with pytest.raises(BrowserUnavailable):
        supervisor.adopt_binding(replace(BINDING, generation="g2"))
    assert lifecycle.binding == BINDING
    assert events == []


@pytest.mark.parametrize("operation", ["stop", "suspend", "wake"])
def test_fence_failure_blocks_other_mutating_lifecycle_paths(tmp_path, operation):
    events = []
    lifecycle = OwnerBoundLifecycle(BINDING, tmp_path / "tabs.json")
    if operation != "wake":
        lifecycle.start(BINDING)
        lifecycle.mark_ready(BINDING)
    before = lifecycle.state
    browser = SimpleNamespace(
        readiness=lambda: BrowserReadiness("alice", "g1", True),
        stop=lambda: events.append("stop"), start=lambda: events.append("start"),
        list_page_urls=lambda: events.append("read"),
    )
    def fail(_):
        raise BrowserUnavailable("synthetic timeout")
    supervisor = SlotSupervisor(lifecycle, browser, viewer_fence=fail)
    with pytest.raises(BrowserUnavailable):
        getattr(supervisor, operation)(BINDING)
    assert events == []
    assert lifecycle.state == before
