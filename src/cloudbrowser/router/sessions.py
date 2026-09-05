"""Durable owner-bound session assignment state for the v2 router."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import json
from pathlib import Path
import tempfile
import threading
from typing import Callable, Iterable

from cloudbrowser.browser_slots import BrowserBinding


class SessionStatus(StrEnum):
    """States visible to the router control plane."""

    WAITING = "waiting"
    OFFERED = "offered"
    ACTIVE = "active"
    BACKED_OFF = "backed_off"
    STOPPED = "stopped"
    LEFT = "left"


@dataclass(frozen=True)
class SlotDescriptor:
    """Router metadata for one private slot supervisor."""

    slot_id: str
    supervisor_url: str
    browser_id: str

    def __post_init__(self) -> None:
        for value in (self.slot_id, self.supervisor_url, self.browser_id):
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError("slot descriptor values must be bounded text")
        if not self.supervisor_url.startswith(("http://", "https://")):
            raise ValueError("supervisor_url must use HTTP(S)")


@dataclass(frozen=True)
class RouterSession:
    """Session record; principal IDs remain internal and are never public output."""

    session_id: str
    request_id: str
    principal_id: str
    status: SessionStatus
    enqueued_at: float
    slot_id: str | None = None
    binding: BrowserBinding | None = None
    offer_expires_at: float | None = None
    session_expires_at: float | None = None
    backoff_until: float | None = None

    def public_dict(self, *, now: float = 0.0, position: int | None = None) -> dict[str, object]:
        """Return bounded metadata without principal, binding, URL, or secret values."""
        result: dict[str, object] = {
            "session_id": self.session_id,
            "request_id": self.request_id,
            "status": self.status.value,
        }
        if position is not None:
            result["position"] = position
        if self.slot_id is not None:
            result["slot_id"] = self.slot_id
        if self.offer_expires_at is not None:
            result["offer_ttl_s"] = max(0.0, self.offer_expires_at - now)
        if self.session_expires_at is not None:
            result["session_ttl_s"] = max(0.0, self.session_expires_at - now)
        if self.backoff_until is not None:
            result["backoff_ttl_s"] = max(0.0, self.backoff_until - now)
        return result


class RouterSessionStore:
    """Thread-safe, atomically persisted FIFO assignment store."""

    _LIVE = frozenset({SessionStatus.WAITING, SessionStatus.OFFERED, SessionStatus.ACTIVE, SessionStatus.BACKED_OFF})

    def __init__(
        self,
        path: str | Path,
        *,
        slots: Iterable[SlotDescriptor],
        clock: Callable[[], float],
        offer_ttl_s: float = 60.0,
        session_ttl_s: float = 3600.0,
        backoff_ttl_s: float = 30.0,
    ) -> None:
        self._path = Path(path)
        self._slots = tuple(slots)
        if not self._slots:
            raise ValueError("at least one slot is required")
        if len({slot.slot_id for slot in self._slots}) != len(self._slots):
            raise ValueError("slot IDs must be unique")
        if len({slot.browser_id for slot in self._slots}) != len(self._slots):
            raise ValueError("browser IDs must be unique")
        for value, name in (
            (offer_ttl_s, "offer_ttl_s"),
            (session_ttl_s, "session_ttl_s"),
            (backoff_ttl_s, "backoff_ttl_s"),
        ):
            if not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be positive")
        self._clock = clock
        self._offer_ttl_s = float(offer_ttl_s)
        self._session_ttl_s = float(session_ttl_s)
        self._backoff_ttl_s = float(backoff_ttl_s)
        self._lock = threading.RLock()
        self._next_sequence = 1
        self._sessions: dict[str, RouterSession] = {}
        self._load()

    def enqueue(self, principal_id: str, *, request_id: str) -> RouterSession:
        with self._lock:
            self._validate_text(principal_id, "principal_id")
            self._validate_text(request_id, "request_id")
            self._expire_locked()
            current = self.for_principal(principal_id)
            if current is not None:
                return current
            record = RouterSession(
                session_id=self._new_id_locked(),
                request_id=request_id,
                principal_id=principal_id,
                status=SessionStatus.WAITING,
                enqueued_at=self._clock(),
            )
            self._sessions[record.session_id] = record
            self._assign_waiters_locked()
            self._persist_locked()
            return self._sessions[record.session_id]

    def activate(self, session_id: str) -> RouterSession:
        with self._lock:
            record = self._require_locked(session_id)
            if record.status is not SessionStatus.OFFERED:
                raise ValueError("only offered sessions can activate")
            record = replace(
                record,
                status=SessionStatus.ACTIVE,
                offer_expires_at=None,
                session_expires_at=self._clock() + self._session_ttl_s,
            )
            self._sessions[session_id] = record
            self._persist_locked()
            return record

    def leave(self, session_id: str) -> RouterSession:
        with self._lock:
            record = self._require_locked(session_id)
            record = replace(
                record,
                status=SessionStatus.LEFT,
                slot_id=None,
                binding=None,
                offer_expires_at=None,
                session_expires_at=None,
            )
            self._sessions[session_id] = record
            self._persist_locked()
            return record

    def backoff(self, session_id: str) -> RouterSession:
        with self._lock:
            record = self._require_locked(session_id)
            record = replace(
                record,
                status=SessionStatus.BACKED_OFF,
                slot_id=None,
                binding=None,
                offer_expires_at=None,
                backoff_until=self._clock() + self._backoff_ttl_s,
            )
            self._sessions[session_id] = record
            self._assign_waiters_locked()
            self._persist_locked()
            return record

    def promote_next(self) -> RouterSession | None:
        with self._lock:
            self._expire_locked()
            occupied = {
                record.slot_id
                for record in self._sessions.values()
                if record.status in {SessionStatus.OFFERED, SessionStatus.ACTIVE}
            }
            waiting = sorted(
                (record for record in self._sessions.values() if record.status is SessionStatus.WAITING),
                key=lambda record: (record.enqueued_at, record.session_id),
            )
            free = [slot for slot in self._slots if slot.slot_id not in occupied]
            if not waiting or not free:
                return None
            record = waiting[0]
            slot = free[0]
            binding = BrowserBinding(
                profile_id=f"profile-{record.principal_id}",
                principal_id=record.principal_id,
                browser_id=slot.browser_id,
                generation=f"generation-{record.session_id}",
            )
            promoted = replace(
                record,
                status=SessionStatus.OFFERED,
                slot_id=slot.slot_id,
                binding=binding,
                offer_expires_at=self._clock() + self._offer_ttl_s,
            )
            self._sessions[record.session_id] = promoted
            self._persist_locked()
            return promoted

    def get(self, session_id: str) -> RouterSession | None:
        with self._lock:
            changed = self._expire_locked()
            record = self._sessions.get(session_id)
            if changed:
                self._persist_locked()
            return record

    def for_principal(self, principal_id: str) -> RouterSession | None:
        self._validate_text(principal_id, "principal_id")
        candidates = [
            record
            for record in self._sessions.values()
            if record.principal_id == principal_id and record.status in self._LIVE
        ]
        if not candidates:
            return None
        order = {
            SessionStatus.ACTIVE: 0,
            SessionStatus.OFFERED: 1,
            SessionStatus.WAITING: 2,
            SessionStatus.BACKED_OFF: 3,
        }
        return min(candidates, key=lambda record: (order[record.status], -record.enqueued_at))

    def position_for(self, session_id: str) -> int | None:
        with self._lock:
            record = self._require_locked(session_id)
            if record.status is not SessionStatus.WAITING:
                return None
            waiting = sorted(
                (item for item in self._sessions.values() if item.status is SessionStatus.WAITING),
                key=lambda item: (item.enqueued_at, item.session_id),
            )
            return next(
                (index for index, item in enumerate(waiting, start=1) if item.session_id == session_id),
                None,
            )

    def slots(self) -> tuple[SlotDescriptor, ...]:
        return self._slots

    def _assign_waiters_locked(self) -> None:
        occupied = {
            record.slot_id
            for record in self._sessions.values()
            if record.status in {SessionStatus.OFFERED, SessionStatus.ACTIVE}
        }
        free = [slot for slot in self._slots if slot.slot_id not in occupied]
        waiting = sorted(
            (record for record in self._sessions.values() if record.status is SessionStatus.WAITING),
            key=lambda record: (record.enqueued_at, record.session_id),
        )
        now = self._clock()
        for record, slot in zip(waiting, free):
            binding = BrowserBinding(
                profile_id=f"profile-{record.principal_id}",
                principal_id=record.principal_id,
                browser_id=slot.browser_id,
                generation=f"generation-{record.session_id}",
            )
            self._sessions[record.session_id] = replace(
                record,
                status=SessionStatus.OFFERED,
                slot_id=slot.slot_id,
                binding=binding,
                offer_expires_at=now + self._offer_ttl_s,
            )

    def _expire_locked(self) -> bool:
        now = self._clock()
        changed = False
        for record in tuple(self._sessions.values()):
            if record.status is SessionStatus.OFFERED and record.offer_expires_at is not None and now >= record.offer_expires_at:
                self._sessions[record.session_id] = replace(
                    record,
                    status=SessionStatus.WAITING,
                    slot_id=None,
                    binding=None,
                    offer_expires_at=None,
                )
                changed = True
            elif record.status is SessionStatus.ACTIVE and record.session_expires_at is not None and now >= record.session_expires_at:
                self._sessions[record.session_id] = replace(
                    record,
                    status=SessionStatus.STOPPED,
                    slot_id=None,
                    binding=None,
                    session_expires_at=None,
                )
                changed = True
            elif record.status is SessionStatus.BACKED_OFF and record.backoff_until is not None and now >= record.backoff_until:
                self._sessions[record.session_id] = replace(record, status=SessionStatus.WAITING, backoff_until=None)
                changed = True
        return changed

    def _new_id_locked(self) -> str:
        while True:
            session_id = f"q-{self._next_sequence}"
            self._next_sequence += 1
            if session_id not in self._sessions:
                return session_id

    def _require_locked(self, session_id: str) -> RouterSession:
        self._validate_text(session_id, "session_id")
        record = self._sessions.get(session_id)
        if record is None:
            raise KeyError("session not found")
        return record

    @staticmethod
    def _validate_text(value: str, name: str) -> None:
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError(f"{name} is invalid")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError(f"{name} is invalid")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            sessions = document["sessions"]
            next_sequence = document["next_sequence"]
            if not isinstance(sessions, list) or not isinstance(next_sequence, int) or next_sequence < 1:
                raise ValueError
            for item in sessions:
                record = self._decode(item)
                current = self._sessions.get(record.principal_id)
                if current is None or self._survivor_rank(record) < self._survivor_rank(current):
                    self._sessions[record.session_id] = record
            self._next_sequence = next_sequence
            for session_id in self._sessions:
                if session_id.startswith("q-"):
                    try:
                        self._next_sequence = max(self._next_sequence, int(session_id[2:]) + 1)
                    except ValueError:
                        pass
            self._expire_locked()
            self._assign_waiters_locked()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("router state is invalid") from exc

    @staticmethod
    def _survivor_rank(record: RouterSession) -> tuple[int, float]:
        rank = {
            SessionStatus.ACTIVE: 0,
            SessionStatus.OFFERED: 1,
            SessionStatus.WAITING: 2,
            SessionStatus.BACKED_OFF: 3,
            SessionStatus.STOPPED: 4,
            SessionStatus.LEFT: 5,
        }
        return rank.get(record.status, 99), -record.enqueued_at

    def _decode(self, item: object) -> RouterSession:
        if not isinstance(item, dict):
            raise ValueError
        session_id = item["session_id"]
        request_id = item["request_id"]
        principal_id = item["principal_id"]
        status = SessionStatus(item["status"])
        for value, name in ((session_id, "session_id"), (request_id, "request_id"), (principal_id, "principal_id")):
            self._validate_text(value, name)
        binding_raw = item.get("binding")
        binding = None
        if binding_raw is not None:
            if not isinstance(binding_raw, dict):
                raise ValueError
            binding = BrowserBinding(
                profile_id=binding_raw["profile_id"],
                principal_id=binding_raw["principal_id"],
                browser_id=binding_raw["browser_id"],
                generation=binding_raw["generation"],
            )
            if binding.principal_id != principal_id:
                raise ValueError
        slot_id = item.get("slot_id")
        if slot_id is not None:
            self._validate_text(slot_id, "slot_id")
        return RouterSession(
            session_id=session_id,
            request_id=request_id,
            principal_id=principal_id,
            status=status,
            enqueued_at=float(item["enqueued_at"]),
            slot_id=slot_id,
            binding=binding,
            offer_expires_at=_optional_float(item.get("offer_expires_at")),
            session_expires_at=_optional_float(item.get("session_expires_at")),
            backoff_until=_optional_float(item.get("backoff_until")),
        )

    def _persist_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "version": 1,
            "next_sequence": self._next_sequence,
            "sessions": [self._encode(record) for record in self._sessions.values()],
        }
        data = json.dumps(document, separators=(",", ":"), sort_keys=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self._path.parent, prefix=f".{self._path.name}.", delete=False
        ) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        temporary.replace(self._path)

    @staticmethod
    def _encode(record: RouterSession) -> dict[str, object]:
        binding = record.binding
        return {
            "session_id": record.session_id,
            "request_id": record.request_id,
            "principal_id": record.principal_id,
            "status": record.status.value,
            "enqueued_at": record.enqueued_at,
            "slot_id": record.slot_id,
            "binding": None
            if binding is None
            else {
                "profile_id": binding.profile_id,
                "principal_id": binding.principal_id,
                "browser_id": binding.browser_id,
                "generation": binding.generation,
            },
            "offer_expires_at": record.offer_expires_at,
            "session_expires_at": record.session_expires_at,
            "backoff_until": record.backoff_until,
        }


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


__all__ = ["RouterSession", "RouterSessionStore", "SessionStatus", "SlotDescriptor"]
