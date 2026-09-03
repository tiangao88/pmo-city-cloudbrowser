"""Own the Chromium process for one isolated, owner-bound browser profile."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Callable
from urllib.parse import urlsplit

from .transport import BrowserUnavailable


class BrowserProcessError(BrowserUnavailable):
    """Raised when the browser process cannot be safely operated."""


@dataclass(frozen=True)
class BrowserProcessConfig:
    """Validated command and identity configuration for one browser process."""

    executable: str
    profile_dir: Path
    http_port: int
    owner: str
    generation: str
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    startup_timeout_s: float = 30.0
    stop_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.executable, str) or not self.executable:
            raise ValueError("executable is required")
        if not self.executable.startswith("/"):
            raise ValueError("executable must be an absolute path")
        if not isinstance(self.profile_dir, Path) or not self.profile_dir.is_absolute():
            raise ValueError("profile_dir must be an absolute path")
        if not isinstance(self.http_port, int) or not 1 <= self.http_port <= 65535:
            raise ValueError("http_port must be between 1 and 65535")
        if not isinstance(self.owner, str) or not self.owner:
            raise ValueError("owner is required")
        if not isinstance(self.generation, str) or not self.generation:
            raise ValueError("generation is required")
        if self.startup_timeout_s <= 0 or self.stop_timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        forbidden_prefixes = (
            "--remote-debugging-address=",
            "--remote-debugging-port=",
            "--user-data-dir=",
        )
        if any(argument.startswith(forbidden_prefixes) for argument in self.extra_args):
            raise ValueError("debugging endpoint and profile are service-owned")

    def command(self) -> list[str]:
        """Build a private, profile-isolated Chromium command."""
        return [
            self.executable,
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={self.http_port}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            *self.extra_args,
        ]


class BrowserProcess:
    """Synchronous process owner with conservative crash recovery."""

    def __init__(
        self,
        config: BrowserProcessConfig,
        *,
        popen: Callable[..., object] = subprocess.Popen,
        probe: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._popen = popen
        self._probe = probe or (lambda: False)
        self._sleep = sleep
        self._monotonic = monotonic
        self._process: object | None = None
        self._state = "stopped"
        self._recovering = False

    @property
    def state(self) -> str:
        process = self._process
        if process is not None and self._poll(process) is not None and self._state == "ready":
            self._state = "failed"
        return self._state

    @property
    def binding(self) -> tuple[str, str]:
        return self.config.owner, self.config.generation

    @property
    def pid(self) -> int | None:
        value = getattr(self._process, "pid", None)
        return value if isinstance(value, int) else None

    def start(self, *, owner: str | None = None, generation: str | None = None) -> bool:
        if owner is not None and owner != self.config.owner:
            raise BrowserProcessError("browser owner binding mismatch")
        if generation is not None and generation != self.config.generation:
            raise BrowserProcessError("browser generation binding mismatch")
        if self.state == "ready":
            return True
        if self.state == "starting":
            raise BrowserProcessError("browser is already starting")
        self.config.profile_dir.mkdir(parents=True, exist_ok=True)
        self._clear_stale_profile_locks()
        self._state = "starting"
        try:
            self._process = self._popen(
                self.config.command(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except (OSError, TypeError) as exc:
            self._process = None
            self._state = "failed"
            raise BrowserProcessError("browser process failed to start") from exc
        deadline = self._monotonic() + self.config.startup_timeout_s
        while self._monotonic() < deadline:
            process = self._process
            if process is None or self._poll(process) is not None:
                self._state = "failed"
                raise BrowserProcessError("browser process exited during startup")
            try:
                if self._probe():
                    self._state = "ready"
                    return True
            except Exception:
                pass
            remaining = max(0.0, deadline - self._monotonic())
            self._sleep(min(0.1, remaining))
        self._state = "failed"
        self._terminate_process()
        raise BrowserProcessError("browser readiness timed out")

    def stop(self) -> None:
        process = self._process
        if process is None:
            self._state = "stopped"
            return
        self._terminate_process()
        self._process = None
        self._state = "stopped"

    def recover_if_crashed(self) -> bool:
        """Restart once after an observed crash; never changes identity binding."""
        process = self._process
        if process is None or self._poll(process) is None:
            return False
        if self._recovering:
            self._state = "failed"
            return False
        self._recovering = True
        try:
            self._process = None
            self._state = "failed"
            return self.start(owner=self.config.owner, generation=self.config.generation)
        finally:
            self._recovering = False

    def watch(self, stop_event: object, *, interval_s: float = 1.0) -> None:
        """Monitor the child and attempt recovery until ``stop_event`` is set."""
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        wait = getattr(stop_event, "wait", None)
        if not callable(wait):
            raise TypeError("stop_event must provide wait(seconds)")
        while not wait(interval_s):
            process = self._process
            if process is None or self._poll(process) is None:
                continue
            try:
                self.recover_if_crashed()
            except BrowserProcessError:
                self._state = "failed"

    def readiness(self) -> bool:
        if self.state != "ready":
            return False
        try:
            return bool(self._probe())
        except Exception:
            return False

    @staticmethod
    def _poll(process: object) -> int | None:
        poll = getattr(process, "poll", None)
        if not callable(poll):
            return None
        result = poll()
        return result if isinstance(result, int) else None

    def _terminate_process(self) -> None:
        process = self._process
        if process is None:
            return
        terminate = getattr(process, "terminate", None)
        wait = getattr(process, "wait", None)
        kill = getattr(process, "kill", None)
        if callable(terminate):
            terminate()
        if callable(wait):
            try:
                wait(timeout=self.config.stop_timeout_s)
                return
            except (TimeoutError, subprocess.TimeoutExpired, OSError):
                pass
        if callable(kill):
            kill()
            if callable(wait):
                try:
                    wait(timeout=self.config.stop_timeout_s)
                except (TimeoutError, subprocess.TimeoutExpired, OSError):
                    pass

    def _clear_stale_profile_locks(self) -> None:
        """Remove Chromium singleton links left by an unclean container exit."""
        for name in ("SingletonCookie", "SingletonLock", "SingletonSocket"):
            marker = self.config.profile_dir / name
            try:
                marker.unlink(missing_ok=True)
            except OSError as exc:
                raise BrowserProcessError("browser profile lock cleanup failed") from exc


def chrome_version_is_ready(raw: object) -> bool:
    """Validate the minimum real Chrome CDP identity response."""
    if not isinstance(raw, dict):
        return False
    browser = raw.get("Browser")
    websocket = raw.get("webSocketDebuggerUrl")
    if not isinstance(browser, str) or not browser:
        return False
    if not isinstance(websocket, str):
        return False
    parsed = urlsplit(websocket)
    return parsed.scheme in {"ws", "wss"} and bool(parsed.netloc)


def browser_process_health(
    *,
    component: str,
    instance_id: str,
    release_version: str,
    state: str,
    owner: str,
    generation: str,
) -> dict[str, str]:
    """Return bounded process metadata suitable for health probes."""
    values = {
        "status": "ok" if state == "ready" else "degraded",
        "component": component,
        "instance_id": instance_id,
        "release_version": release_version,
        "browser_state": state,
        "owner": owner,
        "generation": generation,
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("browser health metadata must be non-empty text")
    return values
