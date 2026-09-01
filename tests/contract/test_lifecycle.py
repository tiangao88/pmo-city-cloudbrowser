from pathlib import Path

import pytest

from cloudbrowser.browser_slots.lifecycle import (
    BrowserBinding,
    BrowserState,
    LifecycleError,
    OwnerBoundLifecycle,
)


BINDING = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")


def lifecycle(tmp_path: Path) -> OwnerBoundLifecycle:
    return OwnerBoundLifecycle(BINDING, tmp_path / "tab-snapshot.json")


def ready_lifecycle(tmp_path: Path) -> OwnerBoundLifecycle:
    value = lifecycle(tmp_path)
    value.start(BINDING)
    value.mark_ready(BINDING)
    return value


def test_lifecycle_requires_start_before_ready_and_is_owner_bound(tmp_path: Path):
    value = lifecycle(tmp_path)
    assert value.state == BrowserState.STOPPED
    assert value.start(BINDING).state == BrowserState.STARTING
    assert value.mark_ready(BINDING).state == BrowserState.READY
    with pytest.raises(LifecycleError):
        value.suspend(BrowserBinding("profile-b", "principal-b", "browser-b", "g2"))


def test_lifecycle_rejects_invalid_transitions(tmp_path: Path):
    value = lifecycle(tmp_path)
    with pytest.raises(LifecycleError):
        value.mark_ready(BINDING)
    with pytest.raises(LifecycleError):
        value.suspend(BINDING)


def test_record_tabs_deduplicates_and_persists_only_http_urls(tmp_path: Path):
    value = ready_lifecycle(tmp_path)
    snapshot = value.record_tabs(
        BINDING,
        [
            "chrome://newtab/",
            "https://example.test/a",
            "https://example.test/a",
            "ftp://example.test/no",
            "http://other.test/b",
        ],
    )
    assert snapshot.urls == ("https://example.test/a", "http://other.test/b")
    assert value.load_tabs(BINDING) == snapshot.urls
    assert value.last_good_snapshot_path.is_file()


def test_malformed_live_snapshot_falls_back_to_last_good(tmp_path: Path):
    value = ready_lifecycle(tmp_path)
    value.record_tabs(BINDING, ["https://example.test/a"])
    (tmp_path / "tab-snapshot.json").write_text("not-json", encoding="utf-8")
    assert value.load_tabs(BINDING) == ("https://example.test/a",)


def test_valid_empty_live_snapshot_is_authoritative(tmp_path: Path):
    value = ready_lifecycle(tmp_path)
    value.record_tabs(BINDING, ["https://example.test/a"])
    (tmp_path / "tab-snapshot.json").write_text(
        '{"browser_id":"browser-a","generation":"g1","principal_id":"principal-a",'
        '"profile_id":"profile-a","state":"ready","urls":[]}',
        encoding="utf-8",
    )
    assert value.load_tabs(BINDING) == ()


def test_snapshot_is_rejected_after_generation_changes(tmp_path: Path):
    value = ready_lifecycle(tmp_path)
    value.record_tabs(BINDING, ["https://example.test/a"])
    changed = BrowserBinding("profile-a", "principal-a", "browser-a", "g2")
    with pytest.raises(LifecycleError):
        value.load_tabs(changed)
