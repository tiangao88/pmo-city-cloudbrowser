"""Own the Chromium process for one isolated, owner-bound browser profile."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import threading
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit

from .transport import BrowserUnavailable
from cloudbrowser.owner_storage import owner_directory, prepare_owner_directory


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
    profile_root: Path | None = None
    download_root: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.executable, str) or not self.executable:
            raise ValueError("executable is required")
        if not self.executable.startswith("/"):
            raise ValueError("executable must be an absolute path")
        if not isinstance(self.profile_dir, Path) or not self.profile_dir.is_absolute():
            raise ValueError("profile_dir must be an absolute path")
        if self.profile_root is not None and not self.profile_root.is_absolute():
            raise ValueError("profile_root must be absolute")
        if self.download_root is not None and (self.profile_root is None or not self.download_root.is_absolute()):
            raise ValueError("download_root requires an absolute owner profile root")
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
            *(("--restore-last-session",) if self.profile_root is not None else ()),
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
        graceful_shutdown: Callable[[], None] | None = None,
    ) -> None:
        self.config = self._owner_config(config)
        self._profile_lease: int | None = None
        self._popen = popen
        self._probe = probe or (lambda: False)
        self._sleep = sleep
        self._monotonic = monotonic
        self._graceful_shutdown = graceful_shutdown
        self._process: object | None = None
        self._state = "stopped"
        self._recovering = False
        self._lock = threading.RLock()
        self._start_epoch = 0

    @staticmethod
    def _owner_config(config: BrowserProcessConfig) -> BrowserProcessConfig:
        if config.profile_root is None:
            return config
        return replace(
            config,
            profile_dir=owner_directory(config.profile_root, config.owner, config.profile_id),
            download_dir=owner_directory(config.download_root, config.owner, config.profile_id) if config.download_root is not None else config.download_dir,
        )

    def _prepare_downloads(self) -> None:
        if self.config.download_root is None or self.config.download_dir is None:
            return
        prepare_owner_directory(self.config.download_root, self.config.download_dir)
        default = self.config.profile_dir / "Default"
        if default.is_symlink():
            raise BrowserProcessError("profile preferences path is invalid")
        default.mkdir(mode=0o700, exist_ok=True)
        path = default / "Preferences"
        if path.is_symlink():
            raise BrowserProcessError("profile preferences path is invalid")
        try:
            document = json.loads(path.read_text()) if path.exists() else {}
            document.setdefault("download", {})["default_directory"] = str(self.config.download_dir)
            document["download"]["prompt_for_download"] = False
            fd, temporary = tempfile.mkstemp(dir=default, prefix=".preferences-")
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(document, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise BrowserProcessError("download preferences are unavailable") from exc

    def _acquire_profile(self) -> None:
        root = self.config.profile_root
        if root is None or self._profile_lease is not None:
            return
        if self.config.owner == "principal-unassigned" or self.config.profile_id == "profile-unassigned":
            raise BrowserProcessError("profile owner is unassigned")
        try:
            prepare_owner_directory(root, self.config.profile_dir)
            descriptor = os.open(self.config.profile_dir / ".cloudbrowser-lease", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BaseException:
                os.close(descriptor)
                raise
            self._profile_lease = descriptor
        except (OSError, ValueError) as exc:
            raise BrowserProcessError("owner profile is unavailable or in use") from exc

    def _release_profile(self) -> None:
        if self._profile_lease is not None:
            os.close(self._profile_lease)
            self._profile_lease = None

    def _strip_identity_cookies(self) -> None:
        if self.config.profile_root is None:
            return
        for relative in ("Default/Cookies", "Default/Network/Cookies"):
            path = self.config.profile_dir / relative
            if not path.exists():
                continue
            if any(p.is_symlink() for p in (path, *path.parents) if p != self.config.profile_root) or not path.resolve().is_relative_to(self.config.profile_dir.resolve()):
                raise BrowserProcessError("profile cookie path is invalid")
            try:
                with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=1.0)) as connection:
                    with connection:
                        connection.execute("DELETE FROM cookies WHERE host_key LIKE '%.pmo.city%' OR host_key LIKE '%aikumi%' OR name LIKE 'tinyauth%'")
            except sqlite3.Error as exc:
                raise BrowserProcessError("identity cookie cleanup failed") from exc

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
            self.config = self._owner_config(replace(
                self.config,
                owner=owner,
                generation=generation,
                profile_id=profile_id if profile_id is not None else self.config.profile_id,
                browser_id=browser_id if browser_id is not None else self.config.browser_id,
            ))

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
            if self._process is not None and self._poll(self._process) is None:
                raise BrowserProcessError("previous browser termination is unconfirmed")
            self._acquire_profile()
            try:
                self.config.profile_dir.mkdir(parents=True, exist_ok=True)
                self._clear_stale_profile_locks()
                self._strip_identity_cookies()
                self._prepare_downloads()
            except BaseException:
                self._release_profile()
                raise
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
                self._release_profile()
                raise BrowserProcessError("browser process failed to start") from exc
            self._process = process
            deadline = self._monotonic() + self.config.startup_timeout_s

        while self._monotonic() < deadline:
            with self._lock:
                if start_epoch != self._start_epoch or self._process is not process:
                    raise BrowserProcessError("browser start was cancelled")
                if self._poll(process) is not None:
                    self._state = "failed"
                    self._release_profile()
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
            self._release_profile()
        raise BrowserProcessError("browser readiness timed out")

    def stop(self) -> None:
        with self._lock:
            self._start_epoch += 1
            process = self._process
            if process is not None:
                # Keep the process gate through termination. A concurrent
                # start must not launch a new browser/profile while the old
                # child still owns the profile and endpoint.
                try:
                    self._terminate_process(process)
                except BaseException:
                    self._state = "failed"
                    raise
            self._process = None
            self._state = "stopped"
            self._release_profile()

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
        if self._poll(process) is None and self._graceful_shutdown is not None and callable(wait):
            try:
                self._graceful_shutdown()
                wait(timeout=self.config.stop_timeout_s)
                return
            except (BrowserUnavailable, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
                # Forced shutdown may leave a singleton requiring recovery.
                pass
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
                    return
                except (TimeoutError, subprocess.TimeoutExpired, OSError):
                    raise BrowserProcessError("browser process did not stop")
        raise BrowserProcessError("browser termination could not be confirmed")

    def _clear_stale_profile_locks(self) -> None:
        """Remove Chromium singleton links left by an unclean container exit."""
        if self.config.profile_root is not None:
            # An orphan Chromium can outlive this service's advisory lease.
            # Fail closed before touching Preferences/Cookies. An operator
            # must prove stale ownership before removing an abandoned marker.
            marker = self.config.profile_dir / "SingletonLock"
            if marker.exists() or marker.is_symlink():
                raise BrowserProcessError("owner profile needs singleton recovery")
            return
        for name in ("SingletonCookie", "SingletonLock", "SingletonSocket"):
            marker = self.config.profile_dir / name
            try:
                marker.unlink(missing_ok=True)
            except OSError as exc:
                raise BrowserProcessError("browser profile lock cleanup failed") from exc


def request_chromium_shutdown(chrome: object) -> None:
    """Private lifecycle-only CDP close: flush tabs/cookies before exit."""
    from .page_actions import _WebSocket

    version = chrome.json_request("/json/version")
    if not chrome_version_is_ready(version):
        raise BrowserProcessError("browser shutdown endpoint is unavailable")
    websocket = _WebSocket(version["webSocketDebuggerUrl"], open_timeout_s=1.0, command_timeout_s=1.0)
    try:
        websocket.send(json.dumps({"id": 1, "method": "Browser.close", "params": {}}))
    finally:
        websocket.close()


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
