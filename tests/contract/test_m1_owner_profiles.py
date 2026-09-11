"""Personal state survives slot changes without transferring to the next owner."""
from dataclasses import replace
from pathlib import Path

import pytest

from cloudbrowser.browser_slots.browser_process import BrowserProcess, BrowserProcessConfig, BrowserProcessError
from cloudbrowser.cloudfiles.browser_downloads import BrowserDownloadWatcher, DownloadWatchConfig
from cloudbrowser.cloudfiles.contracts import PrincipalBinding


class Child:
    pid = 99999999
    returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


def process(root, owner="alice", slot="slot-1"):
    return BrowserProcess(BrowserProcessConfig(
        executable="/usr/bin/chromium", profile_dir=root, profile_root=root,
        owner=owner, profile_id="profile-" + owner, browser_id=slot,
        generation="g1", http_port=9222,
    ), popen=lambda *a, **kw: Child(), probe=lambda: True)


def test_a_b_a_profile_and_slot_recreation(tmp_path):
    p = process(tmp_path)
    p.start()
    alice_dir = p.config.profile_dir
    (alice_dir / "state").write_text("alice-only")
    p.stop()
    p.rebind("bob", "g2", profile_id="profile-bob")
    p.start()
    assert p.config.profile_dir != alice_dir
    assert not (p.config.profile_dir / "state").exists()
    (p.config.profile_dir / "state").write_text("bob-only")
    p.stop()
    fresh = process(tmp_path, slot="slot-2")
    fresh.rebind("alice", "g3", profile_id="profile-alice")
    fresh.start()
    try:
        assert fresh.config.profile_dir == alice_dir
        assert (fresh.config.profile_dir / "state").read_text() == "alice-only"
    finally:
        fresh.stop()


def test_second_slot_cannot_open_live_profile(tmp_path):
    first, second = process(tmp_path), process(tmp_path, slot="slot-2")
    first.start()
    try:
        with pytest.raises(BrowserProcessError):
            second.start()
        assert first.state == "ready"
    finally:
        first.stop()
    second.start()
    second.stop()


def test_prior_unattributed_profile_is_not_adopted(tmp_path):
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "state").write_text("unknown-owner")
    p = process(tmp_path)
    p.start()
    try:
        assert not (p.config.profile_dir / "Default" / "state").exists()
        assert (tmp_path / "Default" / "state").read_text() == "unknown-owner"
    finally:
        p.stop()


def test_profile_symlink_is_rejected(tmp_path):
    p = process(tmp_path / "profiles")
    outside = tmp_path / "outside"
    outside.mkdir()
    p.config.profile_dir.parent.mkdir(parents=True)
    p.config.profile_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises((BrowserProcessError, ValueError, OSError)):
        p.start()


def test_unsubmitted_download_is_never_reattributed(tmp_path):
    alice = PrincipalBinding(principal_id="alice", profile_id="profile-alice", browser_id="s1", generation="g1")
    seen = []
    watcher = BrowserDownloadWatcher(DownloadWatchConfig(
        download_dir=tmp_path, binding=alice, owner_scoped=True,
    ), submit=lambda event: seen.append((event.binding.principal_id, event.source.read())))
    watcher.emit_once()
    alice_path = watcher._config.download_dir
    (alice_path / "report.txt").write_bytes(b"alice-report")
    watcher.update_binding(replace(alice, principal_id="bob", profile_id="profile-bob", generation="g2"))
    watcher.emit_once()
    assert seen == []
    watcher.update_binding(replace(alice, browser_id="s2", generation="g3"))
    watcher.emit_once()
    assert seen == [("alice", b"alice-report")]


def test_managed_singleton_is_preserved_and_blocks_profile_mutation(tmp_path):
    p = process(tmp_path)
    p.config.profile_dir.mkdir(parents=True)
    marker = p.config.profile_dir / "SingletonLock"
    marker.symlink_to("possibly-live-container-999")
    with pytest.raises(BrowserProcessError, match="singleton recovery"):
        p.start()
    assert marker.is_symlink()


def test_identity_cookies_removed_but_application_cookies_preserved(tmp_path):
    import sqlite3

    p = process(tmp_path)
    default = p.config.profile_dir / "Default"
    default.mkdir(parents=True)
    path = default / "Cookies"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE cookies (host_key TEXT, name TEXT)")
        connection.executemany("INSERT INTO cookies VALUES (?, ?)", [
            ("auth.pmo.city", "identity"), ("login.aikumi.example", "session"),
            ("other.example", "tinyauth_session"), ("app.example", "session"),
        ])
    p.start()
    try:
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT * FROM cookies").fetchall() == [("app.example", "session")]
    finally:
        p.stop()


def test_unconfirmed_termination_keeps_exclusive_lease(tmp_path):
    import subprocess

    class Unstoppable(Child):
        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("synthetic", timeout)

    first = process(tmp_path)
    child = Unstoppable()
    first._popen = lambda *args, **kwargs: child
    first.start()
    try:
        with pytest.raises(BrowserProcessError):
            first.stop()
        assert first.state == "failed"
        with pytest.raises(BrowserProcessError, match="termination is unconfirmed"):
            first.start()
        with pytest.raises(BrowserProcessError):
            process(tmp_path, slot="slot-2").start()
    finally:
        # Synthetic process only: make shutdown observable for test cleanup.
        child.wait = lambda **kwargs: 0
        first.stop()
