"""Own the Chromium process for one isolated, owner-bound browser profile."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import signal
import subprocess
import threading
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
    profile_id: str = "profile-unassigned"
    browser_id: str = "browser-unassigned"
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    download_dir: Path | None = None
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
        for value, name in ((self.profile_id, "profile_id"), (self.browser_id, "browser_id")):
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(f"{name} is invalid")
        if self.startup_timeout_s <= 0 or self.stop_timeout_s <= 0:
            raise ValueError("timeouts must be positive")
        forbidden_prefixes = (
            "--remote-debugging-address=",
            "--remote-debugging-port=",
            "--user-data-dir=",
        )
        if any(argument.startswith(forbidden_prefixes) for argument in self.extra_args):
            raise ValueError("debugging endpoint and profile are service-owned")
        if self.download_dir is not None:
            if not isinstance(self.download_dir, Path) or not self.download_dir.is_absolute():
                raise ValueError("download_dir must be an absolute path")
            if any(argument.startswith("--download-dir=") for argument in self.extra_args):
                raise ValueError("download_dir is service-owned")

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
            *(
                (f"--download-dir={self.download_dir}",) if self.download_dir is not None else ()
            ),
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
        self._lock = threading.RLock()
        self._start_epoch = 0

    @property
    def state(self) -> str:
        with self._lock:
            process = self._process
            if process is not None and self._poll(process) is not None and self._state == "ready":
                self._state = "failed"
            return self._state

    @property
    def binding(self) -> tuple[str, str]:
        with self._lock:
            return self.config.owner, self.config.generation

    @property
    def pid(self) -> int | None:
        with self._lock:
            value = getattr(self._process, "pid", None)
            return value if isinstance(value, int) else None

    def rebind(
        self,
        owner: str,
        generation: str,
        *,
        profile_id: str | None = None,
        browser_id: str | None = None,
    ) -> None:
        """Adopt a server-minted binding while the browser is stopped."""

        with self._lock:
            if self.state != "stopped":
                raise BrowserProcessError("browser must be stopped to rebind")
            for value in (owner, generation):
                if not isinstance(value, str) or not value or len(value) > 256:
                    raise ValueError("owner and generation must be bounded strings")
            self.config = replace(
                self.config,
                owner=owner,
                generation=generation,
                profile_id=profile_id if profile_id is not None else self.config.profile_id,
                browser_id=browser_id if browser_id is not None else self.config.browser_id,
            )

    def start(
        self,
        *,
        owner: str | None = None,
        generation: str | None = None,
        _expected_epoch: int | None = None,
    ) -> bool:
        with self._lock:
            if _expected_epoch is not None and _expected_epoch != self._start_epoch:
                raise BrowserProcessError("browser start was cancelled")
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
            self._start_epoch += 1
            start_epoch = self._start_epoch
            try:
                process = self._popen(
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
            self._process = process
            deadline = self._monotonic() + self.config.startup_timeout_s

        while self._monotonic() < deadline:
            with self._lock:
                if start_epoch != self._start_epoch or self._process is not process:
                    raise BrowserProcessError("browser start was cancelled")
                if self._poll(process) is not None:
                    self._state = "failed"
                    raise BrowserProcessError("browser process exited during startup")
            try:
                ready = bool(self._probe())
            except Exception:
                ready = False
            with self._lock:
                if start_epoch != self._start_epoch or self._process is not process:
                    raise BrowserProcessError("browser start was cancelled")
                if ready:
                    self._state = "ready"
                    return True
            remaining = max(0.0, deadline - self._monotonic())
            self._sleep(min(0.1, remaining))

        with self._lock:
            if start_epoch != self._start_epoch or self._process is not process:
                raise BrowserProcessError("browser start was cancelled")
            self._state = "failed"
            self._terminate_process(process)
            if self._process is process:
                self._process = None
        raise BrowserProcessError("browser readiness timed out")

    def stop(self) -> None:
        with self._lock:
            self._start_epoch += 1
            process = self._process
            self._process = None
            self._state = "stopped"
            if process is not None:
                # Keep the process gate through termination. A concurrent
                # start must not launch a new browser/profile while the old
                # child still owns the profile and endpoint.
                self._terminate_process(process)

    def recover_if_crashed(self) -> bool:
        """Restart once after an observed crash; never changes identity binding."""
        with self._lock:
            process = self._process
            if process is None or self._poll(process) is None:
                return False
            if self._recovering:
                self._state = "failed"
                return False
            self._recovering = True
            self._start_epoch += 1
            recovery_epoch = self._start_epoch
            self._process = None
            self._state = "failed"
            owner, generation = self.config.owner, self.config.generation
        try:
            return self.start(
                owner=owner,
                generation=generation,
                _expected_epoch=recovery_epoch,
            )
        finally:
            with self._lock:
                self._recovering = False

    def watch(self, stop_event: object, *, interval_s: float = 1.0) -> None:
        """Monitor the child and attempt recovery until ``stop_event`` is set."""
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        wait = getattr(stop_event, "wait", None)
        if not callable(wait):
            raise TypeError("stop_event must provide wait(seconds)")
        while not wait(interval_s):
            with self._lock:
                process = self._process
                crashed = process is not None and self._poll(process) is not None
            if not crashed:
                continue
            try:
                self.recover_if_crashed()
            except BrowserProcessError:
                with self._lock:
                    if self._state != "stopped":
                        self._state = "failed"

    def readiness(self) -> bool:
        with self._lock:
            if self.state != "ready":
                return False
            process = self._process
        try:
            ready = bool(self._probe())
        except Exception:
            return False
        with self._lock:
            return ready and self._state == "ready" and self._process is process

    @staticmethod
    def _poll(process: object) -> int | None:
        poll = getattr(process, "poll", None)
        if not callable(poll):
            return None
        result = poll()
        return result if isinstance(result, int) else None

    def _terminate_process(self, process: object | None = None) -> None:
        process = self._process if process is None else process
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
    try:
        parsed = urlsplit(websocket)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "ws"
        and hostname in {"127.0.0.1", "localhost", "::1"}
        and port is not None
        and 1 <= port <= 65535
        and bool(parsed.path)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


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
