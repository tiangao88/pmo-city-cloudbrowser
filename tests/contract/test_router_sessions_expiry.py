from __future__ import annotations

from cloudbrowser.router.sessions import RouterSessionStore, SessionStatus, SlotDescriptor


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_expired_offer_returns_to_queue_and_expired_active_stops(tmp_path):
    clock = Clock()
    store = RouterSessionStore(
        tmp_path / "router.json",
        slots=(SlotDescriptor("slot-1", "http://supervisor:8081", "browser-1"),),
        clock=clock,
        offer_ttl_s=1,
        session_ttl_s=20,
    )
    offered = store.enqueue("pmo-owner-a", request_id="req-a")
    assert offered.status is SessionStatus.OFFERED

    clock.now = 1001
    expired_offer = store.get(offered.session_id)
    assert expired_offer is not None
    assert expired_offer.status is SessionStatus.WAITING
    assert store.position_for(expired_offer.session_id) == 1

    promoted = store.promote_next()
    assert promoted is not None
    assert promoted.status is SessionStatus.OFFERED
    active = store.activate(promoted.session_id)
    assert active.status is SessionStatus.ACTIVE

    clock.now = 1030
    expired_active = store.get(active.session_id)
    assert expired_active is not None
    assert expired_active.status is SessionStatus.STOPPED
