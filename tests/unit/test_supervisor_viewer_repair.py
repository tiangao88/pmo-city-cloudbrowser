from types import SimpleNamespace
import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding, OwnerBoundLifecycle
from cloudbrowser.browser_slots.supervisor import SlotSupervisor
from cloudbrowser.browser_slots.transport import BrowserReadiness, BrowserUnavailable


def rig(tmp_path, *, lost):
    binding = BrowserBinding("p", "alice", "b", "g")
    lifecycle = OwnerBoundLifecycle(binding, tmp_path / "tabs.json")
    lifecycle.start(binding)
    lifecycle.mark_ready(binding)
    events = []
    def renew(_):
        events.append("renew")
        if lost:
            raise BrowserUnavailable("viewer lease lost")
    supervisor = SlotSupervisor(lifecycle,
        SimpleNamespace(readiness=lambda: BrowserReadiness("alice", "g", True)),
        viewer_fence=lambda _: events.append("fence"),
        viewer_enable=lambda _: events.append("enable"), viewer_renew=renew)
    return supervisor, binding, events


def test_explicit_ready_wake_repairs_lost_viewer_without_browser_restart(tmp_path):
    supervisor, binding, events = rig(tmp_path, lost=True)
    assert supervisor.wake(binding).status == "ready"
    assert events == ["renew", "fence", "enable"]


def test_healthy_retry_preserves_current_control_mode(tmp_path):
    supervisor, binding, events = rig(tmp_path, lost=False)
    supervisor.wake(binding)
    assert events == ["renew"]


def test_heartbeat_never_reenables_expired_authority(tmp_path):
    supervisor, _, events = rig(tmp_path, lost=True)
    with pytest.raises(BrowserUnavailable):
        supervisor.renew_current_viewer()
    assert events == ["renew"]


def test_failed_repair_propagates_instead_of_returning_ready(tmp_path):
    supervisor, binding, _ = rig(tmp_path, lost=True)
    def failed(_):
        raise BrowserUnavailable("fence unavailable")
    supervisor._viewer_fence = failed
    with pytest.raises(BrowserUnavailable):
        supervisor.wake(binding)
