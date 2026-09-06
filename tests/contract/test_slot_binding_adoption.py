"""RED: per-slot binding adoption for the ingest transport identity chain.

Decision 2026-09-06 (Tigo): option 1+1 — every browser slot gets its file
owner from the slot-supervisor path, never from static container env.

Chain under test:

1. ``SlotSupervisor.adopt_binding`` pushes a new server-derived binding to
   the browser service (``POST /browser/binding``) before wake; the
   lifecycle rejects adoption while a session is ACTIVE.
2. The browser service accepts a trusted-secret-gated binding push and
   updates its process config + adapter identity; untrusted requests fail.
3. The router's ``activate`` dispatch carries the session binding to the
   slot supervisor via ``post_control(..., binding=...)``.
4. The slot-supervisor control API applies the router-provided binding by
   adopting it before waking (matching owner = session principal).
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.browser_slots import (
    BrowserBinding,
    OwnerBoundLifecycle,
    SlotSupervisor,
)
from cloudbrowser.router.control_api import ControlApi, ControlRequest

SECRET = "binding-chain-test-secret-012345"


def _binding(principal: str = "pmo-abc123", generation: str = "generation-s1") -> BrowserBinding:
    return BrowserBinding(
        profile_id=f"profile-{principal}",
        principal_id=principal,
        browser_id="slot-A",
        generation=generation,
    )


class _FakeTransport:
    """Records start/stop calls; pretends the browser came up."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.pushed: list[BrowserBinding] = []
        self.fail_push = False

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def readiness(self):
        from cloudbrowser.browser_slots.transport import BrowserReadiness

        return BrowserReadiness(
            self.pushed[-1].principal_id if self.pushed else "pmo-abc123",
            self.pushed[-1].generation if self.pushed else "generation-s1",
            True,
        )

    def push_binding(self, binding: BrowserBinding) -> None:
        if self.fail_push:
            raise RuntimeError("push rejected")
        self.pushed.append(binding)

    def list_page_urls(self) -> list[str]:
        return []

    def close_empty_pages(self) -> None:
        return None


# ---------------------------------------------------------------------------
# 1. SlotSupervisor.adopt_binding
# ---------------------------------------------------------------------------


def _supervisor(tmp_path: Path, transport: _FakeTransport) -> SlotSupervisor:
    lifecycle = OwnerBoundLifecycle(_binding(), tmp_path / "tabs.json")
    return SlotSupervisor(lifecycle, transport)  # type: ignore[arg-type]


def test_adopt_binding_pushes_to_browser_then_rebinds_lifecycle(tmp_path):
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    new = _binding(principal="pmo-newuser", generation="generation-s2")
    supervisor.adopt_binding(new)
    assert transport.pushed == [new]
    assert supervisor.lifecycle.binding.principal_id == "pmo-newuser"


def test_adopt_binding_requires_same_browser_id(tmp_path):
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    wrong_slot = BrowserBinding(
        profile_id="profile-pmo-x",
        principal_id="pmo-x",
        browser_id="slot-B",
        generation="generation-s9",
    )
    with pytest.raises(ValueError):
        supervisor.adopt_binding(wrong_slot)
    assert transport.pushed == []


def test_adopt_binding_rejected_while_active(tmp_path):
    transport = _FakeTransport()
    supervisor = _supervisor(tmp_path, transport)
    supervisor.wake(_binding())
    with pytest.raises(ValueError):
        supervisor.adopt_binding(_binding(generation="generation-s2"))
    supervisor.suspend(_binding())


def test_adopt_failure_before_push_leaves_lifecycle_untouched(tmp_path):
    transport = _FakeTransport()
    transport.fail_push = True
    supervisor = _supervisor(tmp_path, transport)
    with pytest.raises(RuntimeError):
        supervisor.adopt_binding(_binding(generation="generation-s2"))
    assert supervisor.lifecycle.binding.principal_id == "pmo-abc123"


# ---------------------------------------------------------------------------
# 2. browser service binding-push endpoint
# ---------------------------------------------------------------------------


def test_browser_process_rejects_owner_mismatch_on_start(tmp_path):
    """The process refuses to start under any owner/generation but its own."""
    from cloudbrowser.browser_slots.browser_process import (
        BrowserProcess,
        BrowserProcessConfig,
    )

    config = BrowserProcessConfig(
        executable="/usr/bin/chromium",
        profile_dir=tmp_path / "profile",
        http_port=9222,
        owner="pmo-abc123",
        generation="generation-s1",
    )
    process = BrowserProcess(
        config,
        popen=lambda *a, **k: object(),
        probe=lambda: True,
        sleep=lambda _s: None,
        monotonic=lambda: 0.0,
    )
    with pytest.raises(Exception):
        process.start(owner="pmo-other")
    assert process.start(owner="pmo-abc123", generation="generation-s1") is True
    with pytest.raises(Exception):
        process.start(generation="generation-s2")


def test_rebinding_endpoint_rejects_without_trusted_secret(tmp_path, monkeypatch):
    """The browser /browser/binding route must gate on the shared secret."""
    from cloudbrowser.browser_service import parse_binding_push

    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", SECRET)
    with pytest.raises(PermissionError):
        parse_binding_push(
            {"principal_id": "pmo-abc123", "generation": "generation-s2"},
            provided_secret="wrong-secret-0123456789",
        )


def test_rebinding_endpoint_accepts_matching_secret_and_full_binding(tmp_path, monkeypatch):
    from cloudbrowser.browser_service import parse_binding_push

    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", SECRET)
    binding = parse_binding_push(
        {
            "principal_id": "pmo-abc123",
            "profile_id": "profile-pmo-abc123",
            "browser_id": "slot-A",
            "generation": "generation-s2",
        },
        provided_secret=SECRET,
    )
    assert binding.principal_id == "pmo-abc123"
    assert binding.generation == "generation-s2"


# ---------------------------------------------------------------------------
# 3+4. control-plane binding dispatch
# ---------------------------------------------------------------------------


class _RecordingSupervisor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def wake(self, binding):
        self.calls.append(("wake", {"binding": binding}))
        from cloudbrowser.browser_slots.supervisor import OrchestrationResult
        from cloudbrowser.browser_slots.lifecycle import BrowserState

        return OrchestrationResult(status="ok", state=BrowserState.READY)


def test_control_api_wake_uses_provided_binding():
    supervisor = _RecordingSupervisor()
    api = ControlApi(supervisor, _binding(), trusted_secret=SECRET)  # type: ignore[arg-type]
    result = api.handle(
        ControlRequest(
            operation="wake",
            request_id="req-1",
            binding=_binding(principal="pmo-session", generation="generation-s7"),
        )
    )
    assert result["status"] == "ok"
    assert supervisor.calls[0][1]["binding"].principal_id == "pmo-session"


def test_control_api_rejects_foreign_slot_binding():
    """A router binding for a different browser slot must never be applied."""
    supervisor = _RecordingSupervisor()
    api = ControlApi(supervisor, _binding(), trusted_secret=SECRET)  # type: ignore[arg-type]
    foreign_slot = BrowserBinding(
        profile_id="profile-pmo-someoneelse",
        principal_id="pmo-someoneelse",
        browser_id="slot-B",
        generation="generation-s7",
    )
    result = api.handle(
        ControlRequest(
            operation="wake",
            request_id="req-1",
            binding=foreign_slot,
        )
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "slot_mismatch"
    assert supervisor.calls == []


def test_supervisor_client_sends_binding_on_wake():
    from cloudbrowser.router.supervisor_client import SupervisorClient

    bodies: list[dict] = []

    class _Req:
        def __init__(self, base_url: str, timeout_s: float) -> None:
            pass

        def post(self, body):
            bodies.append(dict(body))
            return 200, json.dumps(
                {"status": "ok", "state": "ready", "restored_count": 0}
            ).encode()

    client = SupervisorClient(
        {"slot-A": "http://supervisor:8093"},
        trusted_secret=SECRET,
        requester_factory=_Req,  # type: ignore[arg-type]
    )
    result = client.post_control(
        "slot-A",
        operation="wake",
        request_id="req-9",
        binding=_binding(principal="pmo-session", generation="generation-s7"),
    )
    assert result["status"] == "ok"
    sent = bodies[0]
    assert sent["binding"]["principal_id"] == "pmo-session"
    assert sent["binding"]["generation"] == "generation-s7"


def test_supervisor_client_omits_binding_when_absent():
    from cloudbrowser.router.supervisor_client import SupervisorClient

    bodies: list[dict] = []

    class _Req:
        def __init__(self, base_url: str, timeout_s: float) -> None:
            pass

        def post(self, body):
            bodies.append(dict(body))
            return 200, json.dumps({"status": "ok", "state": "ready"}).encode()

    client = SupervisorClient(
        {"slot-A": "http://supervisor:8093"},
        trusted_secret=SECRET,
        requester_factory=_Req,  # type: ignore[arg-type]
    )
    client.post_control("slot-A", operation="wake", request_id="req-9")
    assert "binding" not in bodies[0]
