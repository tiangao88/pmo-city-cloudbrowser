from threading import Event, Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding, OwnerBoundLifecycle
from cloudbrowser.browser_slots.supervisor import SlotSupervisor
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer.renewal import ViewerRenewalWorker, configured_viewer_client


def test_settings_default_off_and_partial_settings_rejected():
    assert configured_viewer_client({}) is None
    for settings in (
        {"CB_VIEWER_CONTROL_URL": "http://viewer:8086"},
        {"CB_EXPERIMENTAL_VIEWER_CONTROL": "yes"},
        {"CB_EXPERIMENTAL_VIEWER_CONTROL": "1"},
        {"CB_EXPERIMENTAL_VIEWER_CONTROL": "1", "CB_VIEWER_CONTROL_URL": "http://viewer:8086"},
    ):
        with pytest.raises(ValueError):
            configured_viewer_client(settings)
    assert configured_viewer_client({"CB_EXPERIMENTAL_VIEWER_CONTROL": "1",
        "CB_VIEWER_CONTROL_URL": "http://viewer:8086", "CB_VIEWER_CONTROL_SECRET": "x" * 32})


def test_worker_records_bounded_outcomes_and_does_not_retry_with_enable():
    outcomes = iter([True, False, RuntimeError("sensitive canary")])
    def renew():
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value
    worker = ViewerRenewalWorker(renew)
    for expected in ("renewed", "skipped", "unavailable"):
        worker.tick()
        assert worker.last_outcome == expected
    worker.stop()
    worker.tick()  # Does not invoke the exhausted callback after stop.
    assert worker.last_outcome == "unavailable"


def test_worker_starts_and_stops_without_background_leak():
    called = Event()
    worker = ViewerRenewalWorker(lambda: called.set() or True, interval_s=0.01)
    worker.start()
    try:
        assert called.wait(2)
    finally:
        worker.stop(timeout_s=2)
    with pytest.raises(RuntimeError):
        worker.start()


@pytest.mark.parametrize("interval", [0, -1, 6, float("nan"), float("inf")])
def test_invalid_schedule_rejected(interval):
    with pytest.raises(ValueError):
        ViewerRenewalWorker(lambda: True, interval_s=interval)


def test_supervisor_timer_does_not_queue_behind_lifecycle_transition(tmp_path):
    binding = BrowserBinding("p", "alice", "b", "g1")
    lifecycle = OwnerBoundLifecycle(binding, tmp_path / "tabs.json")
    lifecycle.start(binding)
    lifecycle.mark_ready(binding)
    calls = []
    supervisor = SlotSupervisor(lifecycle,
        SimpleNamespace(readiness=lambda: BrowserReadiness("alice", "g1", True)),
        viewer_fence=lambda _: None, viewer_enable=lambda _: None,
        viewer_renew=lambda b: calls.append(b))
    locked, release = Event(), Event()
    def transition():
        with supervisor._lifecycle_gate:
            locked.set()
            assert release.wait(2)
    thread = Thread(target=transition)
    thread.start()
    try:
        assert locked.wait(2)
        assert supervisor.renew_current_viewer() is False
        assert calls == []
    finally:
        release.set()
        thread.join(2)
    assert supervisor.renew_current_viewer() is True
    assert calls == [binding]
