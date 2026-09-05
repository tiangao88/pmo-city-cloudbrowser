from __future__ import annotations

import json

from cloudbrowser.browser_slots import BrowserBinding
from cloudbrowser.router.sessions import (
    RouterSessionStore,
    SessionStatus,
    SlotDescriptor,
)


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def slots() -> tuple[SlotDescriptor, ...]:
    return (
        SlotDescriptor("slot-1", "http://supervisor-1:8081", "browser-1"),
        SlotDescriptor("slot-2", "http://supervisor-2:8081", "browser-2"),
    )


def test_enqueue_assigns_fifo_sessions_with_opaque_bindings(tmp_path):
    clock = Clock()
    store = RouterSessionStore(tmp_path / "router.json", slots=slots(), clock=clock)

    first = store.enqueue("pmo-owner-a", request_id="req-a")
    second = store.enqueue("pmo-owner-b", request_id="req-b")
    third = store.enqueue("pmo-owner-c", request_id="req-c")

    assert first.status is SessionStatus.OFFERED
    assert second.status is SessionStatus.OFFERED
    assert third.status is SessionStatus.WAITING
    assert first.slot_id == "slot-1"
    assert second.slot_id == "slot-2"
    assert store.position_for(third.session_id) == 1
    assert first.binding == BrowserBinding(
        first.binding.profile_id,
        "pmo-owner-a",
        "browser-1",
        first.binding.generation,
    )
    assert first.binding.principal_id == "pmo-owner-a"
    assert "pmo-owner-a" not in first.public_dict()


def test_activation_and_restart_persist_owner_binding(tmp_path):
    clock = Clock()
    path = tmp_path / "router.json"
    store = RouterSessionStore(path, slots=slots(), clock=clock)
    offered = store.enqueue("pmo-owner-a", request_id="req-a")
    active = store.activate(offered.session_id)

    assert active.status is SessionStatus.ACTIVE
    assert active.session_expires_at is not None
    assert active.session_expires_at > clock.now
    restored = RouterSessionStore(path, slots=slots(), clock=clock)
    observed = restored.for_principal("pmo-owner-a")
    assert observed is not None
    assert observed.status is SessionStatus.ACTIVE
    assert observed.binding == active.binding


def test_leave_releases_slot_and_promotes_oldest_waiter(tmp_path):
    clock = Clock()
    store = RouterSessionStore(tmp_path / "router.json", slots=(slots()[0],), clock=clock)
    active = store.activate(store.enqueue("pmo-owner-a", request_id="req-a").session_id)
    waiting = store.enqueue("pmo-owner-b", request_id="req-b")
    assert waiting.status is SessionStatus.WAITING

    store.leave(active.session_id)
    promoted = store.promote_next()

    assert promoted is not None
    assert promoted.session_id == waiting.session_id
    assert promoted.status is SessionStatus.OFFERED
    assert promoted.binding.principal_id == "pmo-owner-b"


def test_load_heals_duplicate_principal_records_without_changing_sequence(tmp_path):
    path = tmp_path / "router.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "next_sequence": 8,
                "sessions": [
                    {
                        "session_id": "q-2",
                        "request_id": "old",
                        "principal_id": "pmo-owner-a",
                        "status": "waiting",
                        "enqueued_at": 10,
                        "slot_id": None,
                        "binding": None,
                    },
                    {
                        "session_id": "q-7",
                        "request_id": "new",
                        "principal_id": "pmo-owner-a",
                        "status": "active",
                        "enqueued_at": 20,
                        "slot_id": "slot-1",
                        "binding": {
                            "profile_id": "profile-owner-a",
                            "principal_id": "pmo-owner-a",
                            "browser_id": "browser-1",
                            "generation": "generation-7",
                        },
                        "session_expires_at": 2000,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    store = RouterSessionStore(path, slots=(slots()[0],), clock=lambda: 1000.0)
    observed = store.for_principal("pmo-owner-a")

    assert observed is not None
    assert observed.request_id == "new"
    assert observed.status is SessionStatus.ACTIVE
    assert store.enqueue("pmo-owner-b", request_id="req-b").session_id == "q-8"
