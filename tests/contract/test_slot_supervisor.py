from pathlib import Path

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding, BrowserState, OwnerBoundLifecycle
from cloudbrowser.browser_slots.supervisor import ReadinessTimeout, SlotSupervisor
from cloudbrowser.browser_slots.transport import BrowserOwnershipChanged, BrowserReadiness


BINDING = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")
OTHER = BrowserBinding("profile-b", "principal-b", "browser-b", "g2")


class FakeClock:
    def __init__(self, readiness: list[BrowserReadiness]):
        self.now = 0.0
        self.readiness_values = iter(readiness)

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeBrowser:
    def __init__(self, readiness: list[BrowserReadiness], urls: list[str] | None = None):
        self.clock = FakeClock(readiness)
        self.started = 0
        self.stopped = 0
        self.opened: list[str] = []
        self.closed_empty_pages = 0
        self.urls = urls or []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def readiness(self) -> BrowserReadiness:
        try:
            return next(self.clock.readiness_values)
        except StopIteration:
            return BrowserReadiness(BINDING.principal_id, BINDING.generation, False)

    def list_page_urls(self) -> list[str]:
        return list(self.urls)

    def open_page(self, url: str) -> None:
        self.opened.append(url)

    def close_empty_pages(self) -> None:
        self.closed_empty_pages += 1


def supervisor(tmp_path: Path, browser: FakeBrowser) -> SlotSupervisor:
    lifecycle = OwnerBoundLifecycle(BINDING, tmp_path / "tab-snapshot.json")
    return SlotSupervisor(
        lifecycle,
        browser,
        clock=browser.clock.clock,
        sleep=browser.clock.sleep,
    )


def test_wake_waits_for_matching_readiness_and_restores_last_good_tabs(tmp_path: Path):
    seed = OwnerBoundLifecycle(BINDING, tmp_path / "tab-snapshot.json")
    seed.start(BINDING)
    seed.mark_ready(BINDING)
    seed.record_tabs(BINDING, ["https://example.test/a"])

    browser = FakeBrowser(
        [
            BrowserReadiness(BINDING.principal_id, BINDING.generation, False),
            BrowserReadiness(BINDING.principal_id, BINDING.generation, True),
        ]
    )
    result = supervisor(tmp_path, browser).wake(BINDING, timeout_s=2, poll_s=0.5)

    assert result.status == "ready"
    assert result.restored_urls == ("https://example.test/a",)
    assert browser.started == 1
    assert browser.opened == ["https://example.test/a"]
    assert browser.closed_empty_pages == 1


def test_wake_times_out_and_stops_browser(tmp_path: Path):
    browser = FakeBrowser([BrowserReadiness(BINDING.principal_id, BINDING.generation, False)])
    value = supervisor(tmp_path, browser)
    with pytest.raises(ReadinessTimeout):
        value.wake(BINDING, timeout_s=1, poll_s=0.5)
    assert browser.stopped == 1
    assert value.lifecycle.state == BrowserState.STOPPED


def test_wake_fails_closed_when_owner_changes(tmp_path: Path):
    browser = FakeBrowser([BrowserReadiness(OTHER.principal_id, OTHER.generation, True)])
    value = supervisor(tmp_path, browser)
    with pytest.raises(BrowserOwnershipChanged):
        value.wake(BINDING, timeout_s=2, poll_s=0.5)
    assert browser.opened == []
    assert browser.stopped == 1


def test_suspend_snapshots_before_stop_and_requires_matching_transport_owner(tmp_path: Path):
    browser = FakeBrowser(
        [BrowserReadiness(BINDING.principal_id, BINDING.generation, True)],
        urls=["https://example.test/a", "https://example.test/a", "chrome://newtab/"],
    )
    value = supervisor(tmp_path, browser)
    value.wake(BINDING, timeout_s=1, poll_s=0.5)
    result = value.suspend(BINDING)

    assert result.status == "suspended"
    assert result.restored_urls == ("https://example.test/a",)
    assert browser.stopped == 1


def test_recreate_uses_the_same_binding_and_does_not_restore_other_owner(tmp_path: Path):
    browser = FakeBrowser([BrowserReadiness(BINDING.principal_id, BINDING.generation, True)])
    value = supervisor(tmp_path, browser)
    value.wake(BINDING, timeout_s=1, poll_s=0.5)
    with pytest.raises(BrowserOwnershipChanged):
        value.recreate(OTHER, timeout_s=1, poll_s=0.5)
    assert browser.opened == []
