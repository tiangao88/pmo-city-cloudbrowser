"""Session activation: supervisor adopt-then-wake + idempotent re-wake.

The activation slice needs the slot supervisor's HTTP control surface to:

- accept a ``wake`` carrying a server-minted binding different from the
  startup-pinned binding (same ``browser_id``), adopt it first (allowed
  only from STOPPED), then start the browser under the new binding;
- reject a wake carrying a binding for a different ``browser_id`` with
  ``slot_mismatch`` and never touch the lifecycle;
- treat a re-wake of the currently bound, already-ready browser as a
  successful no-op (idempotent), so router retries and activate-after-
  wake converge without restarting or losing the session;
- keep refusing adoption while the slot is not stopped (running browser
  may not be re-bound to another owner).
"""

from __future__ import annotations

from pathlib import Path

from cloudbrowser.browser_slots import (
    BrowserBinding,
    LifecycleError,
    OwnerBoundLifecycle,
    SlotSupervisor,
)
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.router.control_api import ControlApi, ControlRequest


class FakeTransport:
    """Readiness always matches the lifecycle's current binding."""

    def __init__(self) -> None:
        self.started = False
        self.pushed: BrowserBinding | None = None

    def _binding(self) -> BrowserBinding:
        return self._supervisor_ref.lifecycle.binding  # type: ignore[attr-defined]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def readiness(self) -> BrowserReadiness:
        binding = self._binding()
        return BrowserReadiness(
            owner=binding.principal_id, generation=binding.generation, cdp_ok=True
        )

    def list_page_urls(self) -> list[str]:
        return []

    def open_page(self, url: str) -> None:
        return None

    def close_empty_pages(self) -> None:
        return None

    def push_binding(self, binding: BrowserBinding) -> None:
        self.pushed = binding


class _AnnnotatedTransport(FakeTransport):
    """Test seam: keeps a supervisor back-reference for readiness checks."""

    _supervisor_ref: object | None = None


def _stack(tmp_path: Path, *, browser_id: str = "browser-1"):
    pinned = BrowserBinding(
        profile_id="profile-a",
        principal_id="pmo-a",
        browser_id=browser_id,
        generation="generation-A",
    )
    transport = _AnnnotatedTransport()
    lifecycle = OwnerBoundLifecycle(pinned, tmp_path / "tabs.json")
    supervisor = SlotSupervisor(lifecycle, transport)
    transport._supervisor_ref = supervisor
    return ControlApi(supervisor, pinned), supervisor, pinned


def test_wake_with_new_binding_adopts_then_starts(tmp_path):
    api, supervisor, _pinned = _stack(tmp_path)
    minted = BrowserBinding(
        profile_id="profile-b",
        principal_id="pmo-b",
        browser_id="browser-1",
        generation="generation-B",
    )
    result = api.handle(ControlRequest(operation="wake", request_id="req-1", binding=minted))
    assert result == {
        "request_id": "req-1",
        "status": "ready",
        "state": "ready",
        "restored_count": 0,
    }
    assert supervisor.lifecycle.binding == minted
    assert supervisor.lifecycle.state.value == "ready"


def test_wake_with_foreign_browser_id_is_slot_mismatch_and_leaves_slot(tmp_path):
    api, supervisor, _pinned = _stack(tmp_path)
    foreign = BrowserBinding(
        profile_id="profile-b",
        principal_id="pmo-b",
        browser_id="browser-2",
        generation="generation-B",
    )
    result = api.handle(ControlRequest(operation="wake", request_id="req-1", binding=foreign))
    assert result == {
        "request_id": "req-1",
        "status": "failed",
        "error_code": "slot_mismatch",
    }
    assert supervisor.lifecycle.binding.generation == "generation-A"
    assert supervisor.lifecycle.state.value == "stopped"


def test_rewake_of_ready_slot_is_idempotent_ready(tmp_path):
    api, supervisor, pinned = _stack(tmp_path)
    first = api.handle(ControlRequest(operation="wake", request_id="req-1", binding=pinned))
    assert first["status"] == "ready"
    second = api.handle(ControlRequest(operation="wake", request_id="req-2", binding=pinned))
    assert second == {
        "request_id": "req-2",
        "status": "ready",
        "state": "ready",
        "restored_count": 0,
    }
    assert supervisor.lifecycle.state.value == "ready"


def test_rewake_with_minted_binding_after_adopt_is_idempotent(tmp_path):
    api, supervisor, _pinned = _stack(tmp_path)
    minted = BrowserBinding(
        profile_id="profile-b",
        principal_id="pmo-b",
        browser_id="browser-1",
        generation="generation-B",
    )
    first = api.handle(ControlRequest(operation="wake", request_id="req-1", binding=minted))
    assert first["status"] == "ready"
    second = api.handle(ControlRequest(operation="wake", request_id="req-2", binding=minted))
    assert second["status"] == "ready"
    assert second["state"] == "ready"
    assert supervisor.lifecycle.binding == minted


def test_adopt_takes_over_slot_left_running_by_previous_session(tmp_path):
    """Decision 2026-09-08 (Tigo): a session that left the slot running no
    longer wedges the next wake; the supervisor force-stops and adopts. The
    old refused-while-active contract is superseded by the takeover covered
    in tests/contract/test_slot_wake_takeover.py."""
    api, supervisor, pinned = _stack(tmp_path)
    assert api.handle(ControlRequest(operation="wake", request_id="req-1", binding=pinned))[
        "status"
    ] == "ready"
    running_owner = BrowserBinding(
        profile_id="profile-b",
        principal_id="pmo-b",
        browser_id="browser-1",
        generation="generation-B",
    )
    result = api.handle(ControlRequest(operation="wake", request_id="req-2", binding=running_owner))
    assert result["status"] == "ready"
    assert supervisor.lifecycle.binding == running_owner
    assert supervisor.lifecycle.state.value == "ready"
