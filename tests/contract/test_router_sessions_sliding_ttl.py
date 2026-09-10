"""Sliding session TTL: real usage extends the lease; idleness expires it.

The TTL previously ran only from activation, so an actively-driven session
was cut off at the same wall-clock mark as an abandoned one. Renewal happens
on authenticated *work* (agent page actions); passive status polling never
renews, so an untouched open tab still expires on schedule.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from cloudbrowser.router.router_api import RouterApi
from cloudbrowser.router.sessions import RouterSessionStore, SessionStatus, SlotDescriptor


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _slots() -> tuple[SlotDescriptor, ...]:
    return (SlotDescriptor("slot-1", "http://sup-1", "browser-slot-1"),)


class _Identity:
    def resolve(self, identity: object) -> str:
        return "pmo-a"


class _Supervisor:
    known_slots = frozenset({"slot-1"})

    def post_control(self, slot_id: str, *, operation: str, request_id: str, binding=None) -> dict[str, object]:
        return {"status": "ready", "state": "ready", "restored_count": 0}


class _Forwarder:
    known_slots = frozenset({"slot-1"})

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def forward(
        self,
        slot_id: str,
        *,
        binding: object,
        operation: str,
        params: Mapping[str, object],
        request_id: str,
    ) -> dict[str, object]:
        self.calls.append((slot_id, operation))
        return {"status": "ok"}


_HEADERS: Mapping[str, str] = {
    "Remote-Sub": "sub-1",
    "Remote-User": "owner",
    "Remote-Email": "owner@example.com",
    "Remote-Groups": "PMOC_Users",
}


def _api(
    tmp_path: Path, clock: _Clock, forwarder: _Forwarder | None = None
) -> RouterApi:
    store = RouterSessionStore(
        tmp_path / "state.json",
        slots=_slots(),
        clock=clock,
        session_ttl_s=3600.0,
    )
    return RouterApi(
        session_store=store,
        supervisor_client=_Supervisor(),
        identity_client=_Identity(),
        agent_control_forwarder=forwarder,
    )


def test_agent_activity_extends_session_expiry(tmp_path):
    clock = _Clock()
    forwarder = _Forwarder()
    api = _api(tmp_path, clock, forwarder)

    api.open_session(headers=_HEADERS, body={"request_id": "r1"})
    _, activated = api.activate_session(headers=_HEADERS, request_id="r2")
    assert activated["status"] == "active"
    assert activated["session_ttl_s"] == pytest.approx(3600.0)

    # Real work at t=3000 must push the expiry out to t=6600 — not leave it
    # at the original t=4600 mark.
    clock.now = 3000.0
    status, payload = api.agent_action(
        headers=_HEADERS, operation="page_info", body={"request_id": "r3", "params": {"target_tab_id": "tab-1"}}
    )
    assert status == 200
    assert payload["status"] == "ok"
    assert forwarder.calls == [("slot-1", "page_info")]

    _, session = api.get_session(headers=_HEADERS, request_id="r4")
    assert session["status"] == "active"
    assert session["session_ttl_s"] == pytest.approx(3600.0)


def test_idle_session_expires_despite_status_polls(tmp_path):
    clock = _Clock()
    api = _api(tmp_path, clock)

    api.open_session(headers=_HEADERS, body={"request_id": "r1"})
    _, activated = api.activate_session(headers=_HEADERS, request_id="r2")
    assert activated["status"] == "active"
    base_expiry = clock.now + 3600.0

    # Polling alone (the viewer's status loop) never renews: the TTL keeps
    # running down to the original mark.
    for now in (2000.0, 3000.0, 4000.0, 4599.0):
        clock.now = now
        _, session = api.get_session(headers=_HEADERS, request_id="poll")
        assert session["status"] == "active"
        assert session["session_ttl_s"] == pytest.approx(base_expiry - now)

    clock.now = 4600.0
    _, session = api.get_session(headers=_HEADERS, request_id="poll")
    assert session["status"] == "waiting"


def test_store_renew_semantics(tmp_path):
    clock = _Clock()
    store = RouterSessionStore(
        tmp_path / "state.json", slots=_slots(), clock=clock, session_ttl_s=100.0
    )
    first = store.enqueue("pmo-a", request_id="r1")
    assert first.status is SessionStatus.OFFERED
    second = store.enqueue("pmo-b", request_id="r2")
    assert second.status is SessionStatus.WAITING

    # Unknown principal: nothing to renew.
    assert store.renew("pmo-nobody") is None

    # A queued session has no lease to renew and is returned unchanged.
    renewed_b = store.renew("pmo-b")
    assert renewed_b is not None
    assert renewed_b.status is SessionStatus.WAITING
    assert renewed_b.session_expires_at is None

    store.activate(first.session_id)
    clock.now = 1050.0
    renewed = store.renew("pmo-a")
    assert renewed is not None
    assert renewed.status is SessionStatus.ACTIVE
    assert renewed.session_expires_at == pytest.approx(1150.0)


def test_renewed_expiry_survives_restart(tmp_path):
    clock = _Clock()
    path = tmp_path / "state.json"
    store = RouterSessionStore(path, slots=_slots(), clock=clock, session_ttl_s=100.0)
    first = store.enqueue("pmo-a", request_id="r1")
    store.activate(first.session_id)
    clock.now = 1050.0
    store.renew("pmo-a")

    reloaded = RouterSessionStore(
        path, slots=_slots(), clock=clock, session_ttl_s=100.0
    )
    record = reloaded.for_principal("pmo-a")
    assert record is not None
    assert record.session_expires_at == pytest.approx(1150.0)
