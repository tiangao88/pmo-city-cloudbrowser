"""Owner-bound browser lifecycle state primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable
from urllib.parse import urlsplit


class BrowserState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    SUSPENDED = "suspended"
    FAILED = "failed"


class LifecycleError(ValueError):
    """Raised when a lifecycle operation violates the owner binding."""


@dataclass(frozen=True)
class BrowserBinding:
    """Immutable identity binding for one browser profile."""

    profile_id: str
    principal_id: str
    browser_id: str
    generation: str


@dataclass(frozen=True)
class LifecycleSnapshot:
    """Persisted browser lifecycle metadata without secrets or page values."""

    profile_id: str
    principal_id: str
    browser_id: str
    generation: str
    state: BrowserState
    urls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "principal_id": self.principal_id,
            "browser_id": self.browser_id,
            "generation": self.generation,
            "state": self.state.value,
            "urls": list(self.urls),
        }


class OwnerBoundLifecycle:
    """State-only owner-bound lifecycle with durable URL snapshot handling."""

    def __init__(self, binding: BrowserBinding, snapshot_path: Path) -> None:
        self._binding = binding
        self._snapshot_path = Path(snapshot_path)
        self._last_good_path = self._snapshot_path.with_name(
            f"{self._snapshot_path.stem}.last-good{self._snapshot_path.suffix}"
        )
        self._state = BrowserState.STOPPED

    @property
    def binding(self) -> BrowserBinding:
        return self._binding

    @property
    def state(self) -> BrowserState:
        return self._state

    @property
    def last_good_snapshot_path(self) -> Path:
        return self._last_good_path

    def start(self, binding: BrowserBinding) -> LifecycleSnapshot:
        self._require_binding(binding)
        if self._state not in (BrowserState.STOPPED, BrowserState.SUSPENDED, BrowserState.FAILED):
            raise LifecycleError(f"cannot start from {self._state.value}")
        self._state = BrowserState.STARTING
        return self.snapshot()

    def mark_ready(self, binding: BrowserBinding) -> LifecycleSnapshot:
        self._require_binding(binding)
        if self._state != BrowserState.STARTING:
            raise LifecycleError(f"cannot mark ready from {self._state.value}")
        self._state = BrowserState.READY
        return self.snapshot()

    def suspend(self, binding: BrowserBinding) -> LifecycleSnapshot:
        self._require_binding(binding)
        if self._state not in (BrowserState.READY, BrowserState.FAILED):
            raise LifecycleError(f"cannot suspend from {self._state.value}")
        self._state = BrowserState.SUSPENDED
        return self.snapshot()

    def stop(self, binding: BrowserBinding) -> LifecycleSnapshot:
        self._require_binding(binding)
        self._state = BrowserState.STOPPED
        return self.snapshot()

    def record_tabs(self, binding: BrowserBinding, urls: Iterable[str]) -> LifecycleSnapshot:
        self._require_binding(binding)
        if self._state != BrowserState.READY:
            raise LifecycleError("tabs can only be recorded while ready")
        normalized = normalize_urls(urls)
        snapshot = LifecycleSnapshot(
            profile_id=self._binding.profile_id,
            principal_id=self._binding.principal_id,
            browser_id=self._binding.browser_id,
            generation=self._binding.generation,
            state=self._state,
            urls=normalized,
        )
        write_snapshot(self._snapshot_path, snapshot)
        write_snapshot(self._last_good_path, snapshot)
        return snapshot

    def load_tabs(self, binding: BrowserBinding) -> tuple[str, ...]:
        self._require_binding(binding)
        valid, snapshot = read_snapshot(self._snapshot_path, self._binding)
        if valid and snapshot is not None:
            return snapshot.urls
        valid, snapshot = read_snapshot(self._last_good_path, self._binding)
        return snapshot.urls if valid and snapshot is not None else ()

    def snapshot(self) -> LifecycleSnapshot:
        return LifecycleSnapshot(
            profile_id=self._binding.profile_id,
            principal_id=self._binding.principal_id,
            browser_id=self._binding.browser_id,
            generation=self._binding.generation,
            state=self._state,
        )

    def _require_binding(self, binding: BrowserBinding) -> None:
        if binding != self._binding:
            raise LifecycleError("owner or browser binding mismatch")


def normalize_urls(urls: Iterable[str], limit: int = 10) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in urls:
        if not isinstance(value, str):
            continue
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) == limit:
            break
    return tuple(result)


def write_snapshot(path: Path, snapshot: LifecycleSnapshot) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot.to_dict(), separators=(",", ":"), sort_keys=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def read_snapshot(path: Path, binding: BrowserBinding) -> tuple[bool, LifecycleSnapshot | None]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("urls") is None:
            return False, None
        expected = {
            "profile_id": binding.profile_id,
            "principal_id": binding.principal_id,
            "browser_id": binding.browser_id,
            "generation": binding.generation,
        }
        if any(raw.get(key) != value for key, value in expected.items()):
            return False, None
        state = BrowserState(raw["state"])
        raw_urls = raw["urls"]
        if not isinstance(raw_urls, list):
            return False, None
        urls = normalize_urls(raw_urls)
        return True, LifecycleSnapshot(
            profile_id=binding.profile_id,
            principal_id=binding.principal_id,
            browser_id=binding.browser_id,
            generation=binding.generation,
            state=state,
            urls=urls,
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False, None
