from threading import Event, Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer import AuthenticatedViewer, ViewerSessionStore
from cloudbrowser.viewer.desktop_runtime import validate_environment
from cloudbrowser.viewer.interaction import InteractionGate
from cloudbrowser.viewer.slot_authority import SlotViewerAuthority
from cloudbrowser.viewer.transition import ViewerTransition

HEADERS = {"Remote-Sub": "alice-sub", "Remote-Groups": "PMOC_Users"}
BINDING = BrowserBinding("profile", "alice", "browser", "g1")


def rig(broker_jobs=None):
    gate = InteractionGate(broker_jobs=broker_jobs)
    events = []
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=gate.clock), token_secret=b"synthetic-desktop-only")
    authority = SlotViewerAuthority(viewer=viewer,
        identity_client=SimpleNamespace(resolve=lambda i: "alice"),
        readiness=lambda: BrowserReadiness("alice", "g1", True),
        stream_endpoint="/websockify", interaction_gate=gate,
        set_input=lambda enabled: events.append(enabled))
    transition = ViewerTransition(authority, reset_display=lambda: None)
    transition.enable(transition.fence(BINDING), BINDING)
    token = authority.issue_leased(trusted_headers=HEADERS).token
    return gate, authority, token, events


def control(authority, token, action):
    return authority.control(action, trusted_headers=HEADERS, token=token)


def test_takeover_disconnect_stays_paused_until_explicit_resume():
    gate, authority, token, events = rig()
    assert control(authority, token, "takeover") == "human"
    assert events[-1] is True
    for path in ("/agent/page-info", "/broker/login", "/browser/pages/open"):
        assert not gate.permits_browser(path, gate.clock())
    connection = authority.connect(trusted_headers=HEADERS, token=token,
        send_frame=lambda _: None, close_transport=lambda: None)
    with pytest.raises(PermissionError):
        authority.connect(trusted_headers=HEADERS, token=token,
            send_frame=lambda _: None, close_transport=lambda: None)
    connection.revoke()
    assert gate.mode == "paused" and events[-1] is False
    assert control(authority, token, "resume") == "agent"
    assert gate.permits_browser("/agent/page-info", gate.clock())


def test_takeover_drains_operations_already_holding_shared_lock():
    gate, authority, token, _ = rig()
    entered, release, done = Event(), Event(), Event()
    def operation():
        with gate.lock:
            entered.set()
            assert release.wait(2)
    def takeover():
        control(authority, token, "takeover")
        done.set()
    worker, human = Thread(target=operation), Thread(target=takeover)
    worker.start()
    try:
        assert entered.wait(2)
        human.start()
        assert not done.wait(.05)
    finally:
        release.set()
        worker.join(2)
        human.join(2)
    assert done.is_set() and gate.mode == "human"


def test_queued_operation_cannot_execute_after_resume():
    now = [1.0]
    gate = InteractionGate(clock=lambda: now[0])
    gate.change("agent")
    received = now[0]
    now[0] = 2
    gate.change("human", "cookie")
    now[0] = 3
    gate.change("agent")
    assert not gate.permits_browser("/agent/page-info", received)
    assert gate.permits_browser("/agent/page-info", 3)
    assert gate.permits_browser("/browser/stop", received)


def test_input_reset_failure_does_not_resume_agent():
    gate, authority, token, _ = rig()
    control(authority, token, "takeover")
    def fail(_):
        raise RuntimeError("synthetic reset failure")
    authority._set_input = fail
    with pytest.raises(RuntimeError):
        control(authority, token, "resume")
    assert gate.mode == "paused"
    with pytest.raises(PermissionError):
        authority.issue_leased(trusted_headers=HEADERS)


def test_runtime_requires_explicit_credential_free_configuration():
    env = dict(CB_EXPERIMENTAL_DESKTOP="1", CB_EDGE_AUTH="traefik-forwardauth",
        CB_VIEWER_PUBLIC_ORIGIN="https://desktop.example.test", CB_VIEWER_TOKEN_SECRET="a" * 32,
        CB_VIEWER_CONTROL_SECRET="b" * 32, CB_ROUTER_BASE_URL="http://router:8080",
        CB_BROWSER_AUTOSTART="0")
    assert validate_environment(env) == env["CB_VIEWER_PUBLIC_ORIGIN"]
    for key, value in (("CB_EXPERIMENTAL_DESKTOP", "0"), ("CB_EDGE_AUTH", ""),
            ("CB_VIEWER_PUBLIC_ORIGIN", "http://desktop.example.test"),
            ("CB_VIEWER_PUBLIC_ORIGIN", "https://desktop.example.test/path"),
            ("CB_CHROME_EXTRA_ARGS", "--headless=new"), ("CB_BROWSER_AUTOSTART", "1"),
            ("CB_BROKER_SUBMIT_SECRET", "synthetic"), ("CB_VIEWER_CONTROL_SECRET", "a" * 32)):
        with pytest.raises(ValueError):
            validate_environment({**env, key: value})


def test_whole_job_takeover_retry_disconnect_and_resume(tmp_path):
    from cloudbrowser.broker_jobs import BrokerJobs, JobsUnavailable
    jobs = BrokerJobs(tmp_path)
    jobs.claim_authority()
    try:
        gate, authority, token, events = rig(jobs)
        broker = BrokerJobs(tmp_path)
        with broker.job(broker.snapshot()):
            with pytest.raises(JobsUnavailable):
                control(authority, token, "takeover")
            assert gate.mode == "paused" and events[-1] is False
            assert True not in events
            with pytest.raises(JobsUnavailable):
                control(authority, token, "resume")
        assert control(authority, token, "takeover") == "human"
        connection = authority.connect(trusted_headers=HEADERS, token=token,
            send_frame=lambda _: None, close_transport=lambda: None)
        connection.revoke()
        assert gate.mode == "paused" and events[-1] is False
        with pytest.raises(JobsUnavailable):
            broker.snapshot()
        assert control(authority, token, "resume") == "agent"
        assert broker.snapshot()
    finally:
        jobs.close()
