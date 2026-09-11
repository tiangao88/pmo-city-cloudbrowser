"""Regression tests for stale Chromium profile-lock recovery."""

from __future__ import annotations

from pathlib import Path

from cloudbrowser.browser_slots.browser_process import BrowserProcess, BrowserProcessConfig


class FakeProcess:
    pid = 4321

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        return None

    def wait(self, *, timeout: float) -> None:
        return None


def test_browser_process_removes_stale_singleton_markers_before_launch(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    stale_targets = {
        "SingletonCookie": "old-container-cookie",
        "SingletonLock": "old-container-9999",
        "SingletonSocket": "/tmp/org.chromium.Chromium.old/SingletonSocket",
    }
    for name, target in stale_targets.items():
        (profile / name).symlink_to(target)

    popen_calls: list[list[str]] = []

    def popen(command: list[str], **_kwargs: object) -> FakeProcess:
        popen_calls.append(command)
        return FakeProcess()

    process = BrowserProcess(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=profile,
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
        ),
        popen=popen,
        probe=lambda: True,
    )

    assert process.start() is True
    assert popen_calls
    assert not any((profile / name).exists() or (profile / name).is_symlink() for name in stale_targets)
    process.stop()


def test_managed_profile_recovers_singletons_after_lease_aware_launch(tmp_path: Path) -> None:
    root = tmp_path / "profiles"

    def managed_process() -> BrowserProcess:
        return BrowserProcess(
            BrowserProcessConfig(
                executable="/usr/bin/chromium",
                profile_dir=root,
                profile_root=root,
                http_port=9222,
                owner="principal-a",
                profile_id="profile-a",
                generation="generation-a",
            ),
            popen=lambda *_args, **_kwargs: FakeProcess(),
            probe=lambda: True,
        )

    first = managed_process()
    assert first.start() is True
    first.stop()
    profile = first.config.profile_dir
    assert (profile / ".cloudbrowser-singleton-lease-v1").is_file()

    for name, target in {
        "SingletonCookie": "old-cookie",
        "SingletonLock": "old-container-9999",
        "SingletonSocket": "/tmp/old/SingletonSocket",
    }.items():
        (profile / name).symlink_to(target)

    recovered = managed_process()
    assert recovered.start() is True
    assert not any(
        (profile / name).exists() or (profile / name).is_symlink()
        for name in ("SingletonCookie", "SingletonLock", "SingletonSocket")
    )
    recovered.stop()


def test_managed_browser_inherits_profile_lease(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def popen(_command: list[str], **kwargs: object) -> FakeProcess:
        captured.update(kwargs)
        return FakeProcess()

    root = tmp_path / "profiles"
    process = BrowserProcess(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=root,
            profile_root=root,
            http_port=9222,
            owner="principal-a",
            profile_id="profile-a",
            generation="generation-a",
        ),
        popen=popen,
        probe=lambda: True,
    )

    assert process.start() is True
    assert captured["pass_fds"] == (process._profile_lease,)
    process.stop()
