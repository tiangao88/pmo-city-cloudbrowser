"""Self-healing wake: supervisor takes over a slot left running by a dead session.

Decision 2026-09-08 (Tigo): when the router wakes a slot whose lifecycle is
not stopped and holds a foreign binding (the previous session expired or
left without stopping the runtime), the supervisor must force-stop the
running browser and adopt the new server-minted binding instead of wedging
the slot forever. Live incident on dev01 (2026-09-07): session ``q-4`` left
the slot READY with its binding while the router minted ``q-6``; every
control operation then failed with ``operation_failed`` until a manual
container restart.

Guarantees kept:
- A binding naming a different ``browser_id`` is still refused outright.
- If the underlying browser cannot be stopped, adoption fails closed and
  the old binding is untouched.
- The binding push still happens only against a stopped browser, so one
  generation's downloads can never be attributed to another owner.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.browser_slots import (
    BrowserBinding,
    BrowserState,
    OwnerBoundLifecycle,
    SlotSupervisor,
)
from cloudbrowser.router.control_api import ControlApi, ControlRequest

SECRET = "wake-takeover-test-secret-012345"


def _binding(principal: str = "pmo-q4", generation: str = "generation-q-4") -> BrowserBinding:
    return BrowserBinding(
        profile_id=f"profile-{principal}",
        principal_id=principal,
        browser_id="slot-1",
        generation=generation,
    )


class _FakeTransport:
    """Records start/stop/push; readiness mirrors the last pushed binding."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.pushed: list[BrowserBinding] = []
        self.fail_push = False
        self.fail_stop = False

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        if self.fail_stop:
            raise RuntimeError("stop rejected")
        self.stopped += 1

    def readiness(self):
        from cloudbrowser.browser_slots.transport import BrowserReadiness

        current = self.pushed[-1] if self.pushed else _binding()
        return BrowserReadiness(current.principal_id, current.generation, True)

    def push_binding(self, binding: BrowserBinding) -> None:
        if self.fail_push:
            raise RuntimeError("push rejected")
        self.pushed.append(binding)

    def list_page_urls(self) -> list[str]:
        return []

    def close_empty_pages(self) -> None:
        return None


def _supervisor(tmp_path: Path, transport: _FakeTransport) -> SlotSupervisor:
    lifecycle = OwnerBoundLifecycle(_binding(), tmp_path / "tabs.json")
    return SlotSupervisor(lifecycle, transport)  # type: ignore[arg-type]


def test_adopt_binding_takes_over_a_running_foreign_browser(tmp_path: Path) -> None:
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    supervisor.wake(_binding())  # session A is ACTIVE on the slot
    assert supervisor.lifecycle.state is BrowserState.READY

    new = _binding(principal="pmo-q6", generation="generation-q-6")
    supervisor.adopt_binding(new)

    # The stale runtime was stopped, the new binding pushed (while stopped),
    # and the lifecycle rebound to the new session.
    assert transport.stopped == 1
    assert transport.pushed == [new]
    assert supervisor.lifecycle.binding == new
    assert supervisor.lifecycle.state is BrowserState.STOPPED


def test_takeover_then_wake_runs_the_new_session_end_to_end(tmp_path: Path) -> None:
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    supervisor.wake(_binding())

    new = _binding(principal="pmo-q6", generation="generation-q-6")
    supervisor.adopt_binding(new)
    result = supervisor.wake(new)

    assert result.status == "ready"
    assert supervisor.lifecycle.state is BrowserState.READY
    assert transport.started == 2


@pytest.mark.parametrize(
    ("other_principal", "other_generation"),
    [
        ("pmo-q6", "generation-q-6"),
        ("pmo-q4", "generation-q-9"),
    ],
)
def test_takeover_from_every_live_state(
    tmp_path: Path, other_principal: str, other_generation: str
) -> None:
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    supervisor.wake(_binding())
    if other_principal == "pmo-q4":  # exercise the SUSPENDED foreign-binding case
        supervisor.suspend(_binding())

    other = _binding(principal=other_principal, generation=other_generation)
    supervisor.adopt_binding(other)
    assert supervisor.lifecycle.binding == other
    assert supervisor.lifecycle.state is BrowserState.STOPPED
    assert transport.stopped >= 1


def test_takeover_still_refuses_a_different_browser_slot(tmp_path: Path) -> None:
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    supervisor.wake(_binding())

    wrong_slot = BrowserBinding(
        profile_id="profile-pmo-q6",
        principal_id="pmo-q6",
        browser_id="slot-2",
        generation="generation-q-6",
    )
    with pytest.raises(ValueError):
        supervisor.adopt_binding(wrong_slot)
    # No side effects: the running session must stay untouched.
    assert transport.stopped == 0
    assert transport.pushed == []
    assert supervisor.lifecycle.binding == _binding()


def test_takeover_fails_closed_when_the_browser_cannot_be_stopped(tmp_path: Path) -> None:
    transport = _FakeTransport()
    transport.fail_stop = True
    supervisor = _supervisor(tmp_path, transport)
    supervisor.wake(_binding())

    new = _binding(principal="pmo-q6", generation="generation-q-6")
    with pytest.raises(RuntimeError):
        supervisor.adopt_binding(new)

    assert transport.pushed == []
    assert supervisor.lifecycle.binding == _binding()
    assert supervisor.lifecycle.state is BrowserState.READY


def test_control_api_wake_recovers_a_wedged_slot(tmp_path: Path) -> None:
    """Regression test for the dev01 q-4/q-6 wedge, via the control API."""

    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    api = ControlApi(supervisor, _binding(), trusted_secret=SECRET)  # type: ignore[arg-type]

    first = api.handle(ControlRequest(operation="wake", request_id="req-1", binding=_binding()))
    assert first["status"] == "ready"

    # Session q-4 died without stopping the runtime; the router now offers
    # the slot to session q-6 with a freshly minted binding.
    new = _binding(principal="pmo-q6", generation="generation-q-6")
    second = api.handle(ControlRequest(operation="wake", request_id="req-2", binding=new))

    assert second["status"] == "ready"
    assert supervisor.lifecycle.binding == new
    assert supervisor.lifecycle.state is BrowserState.READY
