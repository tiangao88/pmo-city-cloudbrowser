"""Contract tests for the real Chromium-owning browser service."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
import time

import pytest

from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter
from cloudbrowser.browser_slots.browser_process import (
    BrowserProcess,
    BrowserProcessConfig,
    BrowserProcessError,
)
from cloudbrowser.browser_slots.transport import BrowserUnavailable


class FakeChrome:
    def __init__(self, *, ready: bool = True):
        self.ready = ready
        self.calls: list[tuple[str, str]] = []

    def json_request(self, path: str, *, method: str = "GET") -> object:
        self.calls.append((method, path))
        if path == "/json/version" and self.ready:
            return {"Browser": "Chrome/Test", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools"}
        raise BrowserUnavailable("not ready")

    def text_request(self, path: str, *, method: str = "GET") -> str:
        self.calls.append((method, path))
        return "OK"


def test_browser_process_config_requires_explicit_profile_and_safe_binary(tmp_path: Path):
    config = BrowserProcessConfig(
        executable="/usr/bin/chromium",
        profile_dir=tmp_path / "profile",
        http_port=9222,
        owner="principal-a",
        generation="generation-a",
    )
    assert config.profile_dir == tmp_path / "profile"
    assert "--user-data-dir=" + str(tmp_path / "profile") in config.command()
    assert "--remote-debugging-port=9222" in config.command()
    with pytest.raises(ValueError):
        BrowserProcessConfig(
            executable="",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
        )
    with pytest.raises(ValueError):
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
            extra_args=("--remote-debugging-address=0.0.0.0",),
        )


def test_browser_process_lifecycle_is_owner_and_generation_bound(tmp_path: Path):
    marker = tmp_path / "marker"
    executable = tmp_path / "fake-chrome"
    executable.write_text(
        "#!/bin/sh\n"
        f"echo started > {marker}\n"
        "trap 'exit 0' TERM INT\n"
        "while :; do sleep 0.01; done\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    process = BrowserProcess(
        BrowserProcessConfig(
            executable=str(executable),
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
        ),
        popen=subprocess.Popen,
        probe=lambda: True,
        sleep=lambda seconds: time.sleep(min(seconds, 0.01)),
    )
    assert process.start() is True
    assert process.state == "ready"
    assert process.binding == ("principal-a", "generation-a")
    process.stop()
    assert process.state == "stopped"
    with pytest.raises(BrowserProcessError):
        process.start(owner="principal-b", generation="generation-a")


def test_stop_cancels_a_blocked_start_and_cannot_finish_ready(tmp_path: Path) -> None:
    """A concurrent stop wins even when startup is blocked in its readiness probe."""

    probe_entered = threading.Event()
    release_probe = threading.Event()

    class FakePopen:
        pid = 4321

        def __init__(self, *_args, **_kwargs):
            self.returncode = None
            self.terminated = threading.Event()

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0
            self.terminated.set()

        def wait(self, timeout=None):
            assert self.terminated.wait(timeout)
            return 0

        def kill(self):
            self.returncode = -9
            self.terminated.set()

    child: FakePopen | None = None

    def popen(*args, **kwargs):
        nonlocal child
        child = FakePopen(*args, **kwargs)
        return child

    def blocked_probe() -> bool:
        probe_entered.set()
        assert release_probe.wait(2)
        return True

    process = BrowserProcess(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
            startup_timeout_s=2,
        ),
        popen=popen,
        probe=blocked_probe,
    )
    outcome: list[object] = []

    def start() -> None:
        try:
            outcome.append(process.start())
        except BaseException as exc:  # capture the starter thread's bounded cancellation
            outcome.append(exc)

    starter = threading.Thread(target=start)
    stopper = threading.Thread(target=process.stop)
    starter.start()
    assert probe_entered.wait(1)
    stopper.start()
    time.sleep(0.05)
    release_probe.set()
    starter.join(2)
    stopper.join(2)

    assert not starter.is_alive()
    assert not stopper.is_alive()
    assert child is not None and child.terminated.is_set()
    assert process.state == "stopped"
    assert len(outcome) == 1
    assert isinstance(outcome[0], BrowserProcessError)


def test_recovery_cannot_resurrect_after_concurrent_stop(tmp_path: Path) -> None:
    """A stop that wins during crash recovery prevents the old recovery start."""

    recovery_start_entered = threading.Event()
    release_recovery_start = threading.Event()

    class FakePopen:
        def __init__(self, *_args, **_kwargs):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.returncode = -9

    class BlockingRecoveryStart(BrowserProcess):
        def start(self, **kwargs):
            recovery_start_entered.set()
            assert release_recovery_start.wait(2)
            return super().start(**kwargs)

    process = BlockingRecoveryStart(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
        ),
        popen=FakePopen,
        probe=lambda: True,
    )
    crashed = FakePopen()
    crashed.returncode = 1
    process._process = crashed
    process._state = "ready"
    outcome: list[object] = []

    def recover() -> None:
        try:
            outcome.append(process.recover_if_crashed())
        except BaseException as exc:  # capture the bounded cancellation
            outcome.append(exc)

    recovering = threading.Thread(target=recover)
    recovering.start()
    assert recovery_start_entered.wait(1)

    stopper = threading.Thread(target=process.stop)
    stopper.start()
    stopper.join(1)
    assert not stopper.is_alive()

    release_recovery_start.set()
    recovering.join(2)
    assert not recovering.is_alive()
    assert process.state == "stopped"
    assert len(outcome) == 1
    assert isinstance(outcome[0], BrowserProcessError)


def test_browser_process_crash_is_detected_and_recovered(tmp_path: Path):
    starts: list[int] = []

    class FakePopen:
        def __init__(self, *_args, **_kwargs):
            starts.append(1)
            self.returncode = None
            self.crashed = False

        def poll(self):
            if self.crashed:
                return 1
            return None

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.returncode = -9

    process = BrowserProcess(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
        ),
        popen=FakePopen,
        probe=lambda: True,
        sleep=lambda seconds: None,
    )
    assert process.start() is True
    assert process.state == "ready"
    process._process.crashed = True
    assert process.recover_if_crashed() is True
    assert len(starts) == 2
    assert process.state == "ready"


def test_browser_adapter_wires_process_lifecycle_and_real_readiness(tmp_path: Path):
    events: list[str] = []
    fake = FakeChrome()
    process = BrowserProcess(
        BrowserProcessConfig(
            executable="/usr/bin/chromium",
            profile_dir=tmp_path / "profile",
            http_port=9222,
            owner="principal-a",
            generation="generation-a",
        ),
        popen=lambda *_args, **_kwargs: events.append("start") or object(),
        probe=lambda: True,
    )
    adapter = ChromeBrowserAdapter(
        fake,
        owner="principal-a",
        generation="generation-a",
        start_callback=process.start,
        stop_callback=lambda: events.append("stop"),
    )
    adapter.start()
    assert adapter.readiness().cdp_ok is True
    adapter.stop()
    assert events == ["start", "stop"]


def test_browser_health_includes_process_state_without_sensitive_values():
    from cloudbrowser.browser_slots.browser_process import browser_process_health

    payload = browser_process_health(
        component="browser",
        instance_id="cloudbrowser-test",
        release_version="0.2.0-dev1",
        state="ready",
        owner="principal-a",
        generation="generation-a",
    )
    assert payload["status"] == "ok"
    assert payload["browser_state"] == "ready"
    assert payload["owner"] == "principal-a"
    assert payload["generation"] == "generation-a"
    assert "password" not in json.dumps(payload).lower()
    assert "cookie" not in json.dumps(payload).lower()
