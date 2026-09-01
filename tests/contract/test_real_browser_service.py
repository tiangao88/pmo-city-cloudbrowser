"""Contract tests for the real Chromium-owning browser service."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
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
