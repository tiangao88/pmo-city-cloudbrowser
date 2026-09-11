"""Synthetic whole-job coordination, including independent process lifetimes."""
import subprocess
import sys
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.broker_jobs import BrokerJobs, JobsUnavailable
from cloudbrowser.credential_broker.contracts import GrantAuthorization, LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.deadline import BrokerDeadline
from cloudbrowser.credential_broker.service import AdapterResult, ResolvedBinding
from cloudbrowser.viewer.interaction import InteractionGate


@pytest.fixture
def jobs(tmp_path):
    authority = BrokerJobs(tmp_path)
    authority.claim_authority()
    authority.change("agent")
    try:
        yield authority, BrokerJobs(tmp_path)
    finally:
        authority.close()


def coordinator(jobs, fetch, supplies_material):
    binding = ResolvedBinding("profile", "alice", "browser", "site", "g1")
    grant = GrantAuthorization("synthetic", "profile", "alice", "browser", "g1", "site", "tab")
    gate = SimpleNamespace(supplies_material=supplies_material,
        run_authorized=lambda auth, operation: operation(fetch(auth.username_ref)))
    return BrokerCoordinator(resolve_initial=lambda _: binding, resolve_pre_fill=lambda _: binding,
        declarations={"site": SiteDeclaration("site", "https://example.test")},
        grant_resolver=SimpleNamespace(resolve=lambda *_: grant),
        target_preflight=lambda *_: "synthetic-proof",
        adapter_selector=lambda *_: lambda *_: AdapterResult("authenticated", True),
        authorization_gate=gate if supplies_material else None, broker_jobs=jobs)


INTENT = LoginIntent("req", "profile", "alice", "browser", "site",
                     target_tab_id="tab", binding_generation="g1")


@pytest.mark.parametrize("supplies_material", [False, True])
def test_human_blocks_both_fetch_paths_and_stale_queue(jobs, supplies_material):
    authority, broker = jobs
    calls = []
    fetch = lambda _: calls.append("vault") or object()
    service = coordinator(broker, fetch, supplies_material)
    old = service.admission_epoch()
    authority.change("human")
    assert service.execute(INTENT, fetch_credentials=fetch).error_code == "browser_control_paused"
    assert calls == []
    authority.change("agent")
    assert service.execute(INTENT, fetch_credentials=fetch,
                           admission_epoch=old).error_code == "browser_control_paused"
    assert calls == []
    assert service.execute(INTENT, fetch_credentials=fetch).status == "authenticated"
    assert calls == ["vault"]


@pytest.mark.parametrize("supplies_material", [False, True])
def test_deadline_does_not_release_running_fetch(jobs, supplies_material):
    authority, broker = jobs
    entered, release = Event(), Event()
    now = [0.0]
    def fetch(_):
        entered.set()
        assert release.wait(5)
        return object()
    service = coordinator(broker, fetch, supplies_material)
    deadline = BrokerDeadline.from_receipt(receipt_monotonic=0, budget_s=1,
                                           monotonic_clock=lambda: now[0])
    results = []
    worker = Thread(target=lambda: results.append(service.execute(
        INTENT, fetch_credentials=fetch, deadline=deadline)))
    worker.start()
    try:
        assert entered.wait(2)
        now[0] = 2
        gate = InteractionGate(broker_jobs=authority)
        with pytest.raises(JobsUnavailable):
            gate.change("human", "cookie")
        assert gate.mode == "paused"
        with pytest.raises(JobsUnavailable):
            broker.snapshot()
        with pytest.raises(JobsUnavailable):
            gate.change("agent")
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results[0].error_code == "deadline_exceeded"
    authority.change("human")


def test_exception_releases_job_and_authority_loss_denies_admission(jobs):
    authority, broker = jobs
    with pytest.raises(RuntimeError):
        with broker.job(broker.snapshot()):
            raise RuntimeError("synthetic")
    authority.change("human")
    authority.change("agent")
    authority.close()
    with pytest.raises(JobsUnavailable):
        broker.snapshot()


def test_independent_broker_process_death_and_authority_restart(jobs, tmp_path):
    authority, broker = jobs
    old = broker.snapshot()
    child = subprocess.Popen([sys.executable, "-u", "-c", """
import sys
from cloudbrowser.broker_jobs import BrokerJobs
jobs = BrokerJobs(sys.argv[1])
with jobs.job(jobs.snapshot()):
    print('admitted', flush=True)
    sys.stdin.read()
""", str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True)
    try:
        # select keeps a broken child from hanging the test at readline.
        import select
        assert select.select([child.stdout], [], [], 5)[0]
        assert child.stdout.readline().strip() == "admitted"
        authority.close()
        authority.claim_authority()
        with pytest.raises(JobsUnavailable):
            authority.change("agent")
        with pytest.raises(JobsUnavailable):
            authority.change("human")
        child.kill()
        child.communicate(timeout=5)
        authority.change("agent")
        with pytest.raises(JobsUnavailable):
            with broker.job(old):
                pytest.fail("old epoch resumed")
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=5)


def test_missing_corrupt_state_and_duplicate_authority_fail_closed(jobs, tmp_path):
    authority, broker = jobs
    other = BrokerJobs(tmp_path)
    with pytest.raises(BlockingIOError):
        other.claim_authority()
    (tmp_path / "state").write_text("partial")
    with pytest.raises(JobsUnavailable):
        broker.snapshot()
    authority.change("paused")
    with pytest.raises(JobsUnavailable):
        broker.snapshot()


def test_uncertain_agent_state_write_relinquishes_authority(jobs, monkeypatch):
    import os
    authority, broker = jobs
    real_fsync = os.fsync
    writes = []
    def fail_second_write(fd):
        writes.append(fd)
        if len(writes) == 2:
            raise OSError("synthetic durability failure after agent write")
        real_fsync(fd)
    monkeypatch.setattr(os, "fsync", fail_second_write)
    with pytest.raises(OSError):
        authority.change("agent")
    with pytest.raises(JobsUnavailable):
        broker.snapshot()
    with pytest.raises(JobsUnavailable):
        authority.change("human")
