"""Owner-bound slot supervisor orchestration."""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from functools import wraps
from typing import Callable

from .lifecycle import BrowserBinding, BrowserState, LifecycleError, OwnerBoundLifecycle
from .transport import (
    BrowserOwnershipChanged,
    BrowserReadiness,
    BrowserTransport,
    BrowserUnavailable,
)


class ReadinessTimeout(BrowserUnavailable):
    """Raised when a started browser never becomes ready within the deadline."""


def _serialized(operation: Callable) -> Callable:
    """Hold the supervisor's re-entrant gate for one complete transition."""

    @wraps(operation)
    def guarded(self: "SlotSupervisor", *args: object, **kwargs: object) -> object:
        with self._lifecycle_gate:
            return operation(self, *args, **kwargs)

    return guarded


@dataclass(frozen=True)
class OrchestrationResult:
    """Bounded outcome safe for a control-plane caller."""

    status: str
    state: BrowserState
    restored_urls: tuple[str, ...] = ()


class SlotSupervisor:
    """Coordinate lifecycle state with a narrow, owner-bound browser transport."""

    def __init__(
        self,
        lifecycle: OwnerBoundLifecycle,
        transport: BrowserTransport,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        native_tab_restore: bool = False,
        viewer_fence: Callable[[BrowserBinding], None] | None = None,
        viewer_enable: Callable[[BrowserBinding], None] | None = None,
        viewer_renew: Callable[[BrowserBinding], None] | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._native_tab_restore = native_tab_restore
        self._lifecycle_gate = threading.RLock()
        self._viewer_fence = viewer_fence
        if viewer_enable is not None and viewer_fence is None:
            raise ValueError("viewer enable requires fencing")
        self._viewer_enable = viewer_enable
        if viewer_renew is not None and viewer_enable is None:
            raise ValueError("viewer renewal requires enable handshake")
        self._viewer_renew = viewer_renew

    @_serialized
    def renew_viewer(self, binding: BrowserBinding) -> None:
        """Heartbeat hook; runtime must schedule it, never renew blindly."""
        if (self._viewer_renew is None or self._lifecycle.binding != binding
                or self._lifecycle.state is not BrowserState.READY):
            raise BrowserUnavailable("viewer lease renewal unavailable")
        ready = self._transport.readiness()
        if (ready.owner, ready.generation, ready.cdp_ok) != (
            binding.principal_id, binding.generation, True
        ):
            raise BrowserUnavailable("viewer lease renewal unavailable")
        self._viewer_renew(binding)

    def renew_current_viewer(self) -> bool:
        """Timer entry point: never queue a heartbeat behind a slot change."""
        if not self._lifecycle_gate.acquire(blocking=False):
            return False
        try:
            self.renew_viewer(self._lifecycle.binding)
            return True
        finally:
            self._lifecycle_gate.release()

    def _fence_viewer(self, binding: BrowserBinding) -> None:
        if self._viewer_fence is not None:
            self._viewer_fence(binding)

    @property
    def lifecycle(self) -> OwnerBoundLifecycle:
        return self._lifecycle

    @_serialized
    def wake(
        self,
        binding: BrowserBinding,
        *,
        timeout_s: float = 30.0,
        poll_s: float = 0.1,
    ) -> OrchestrationResult:
        """Start the browser, wait for matching readiness, and restore tabs.

        Idempotent for the currently bound, already-ready browser: a re-wake
        of the same binding converges to ``ready`` without restarting, so
        router retries and activate-after-wake never bounce a live session.
        """
        self._require_positive_timeout(timeout_s, poll_s)
        if (
            self._lifecycle.state is BrowserState.READY
            and self._lifecycle.binding == binding
        ):
            try:
                readiness = self._transport.readiness()
            except BrowserUnavailable:
                readiness = None
            if (
                readiness is not None
                and readiness.owner == binding.principal_id
                and readiness.generation == binding.generation
                and readiness.cdp_ok
            ):
                if self._viewer_renew is not None:
                    try:
                        self._viewer_renew(binding)
                    except Exception:
                        # Explicit wake repairs a lost viewer incarnation or
                        # expired lease. Heartbeats never execute this path.
                        self._fence_viewer(binding)
                        self._viewer_enable(binding)
                urls = self._lifecycle.load_tabs(binding)
                return OrchestrationResult("ready", self._lifecycle.state, urls)

            # The supervisor can outlive a restarted browser container. Its
            # in-memory lifecycle then remains READY while the browser process
            # and runtime binding return to their stopped boot values. Stop is
            # idempotent at the browser boundary; push the authoritative
            # server-minted binding while stopped, then restart below. Keep the
            # lifecycle READY until both operations succeed so a transient
            # transport failure remains retryable through this same branch.
            self._fence_viewer(binding)
            self._transport.stop()
            push = getattr(self._transport, "push_binding", None)
            if push is not None:
                push(binding)
            self._lifecycle.stop(binding)
        self._fence_viewer(self._lifecycle.binding)
        self._lifecycle.start(binding)
        try:
            self._transport.start()
            self._wait_ready(binding, timeout_s=timeout_s, poll_s=poll_s)
            self._lifecycle.mark_ready(binding)
            urls = self._lifecycle.load_tabs(binding)
            if not self._native_tab_restore:
                for url in urls:
                    self._transport.open_page(url)
            self._transport.close_empty_pages()
            if self._viewer_enable is not None:
                self._viewer_enable(binding)
            return OrchestrationResult("ready", self._lifecycle.state, urls)
        except (BrowserOwnershipChanged, BrowserUnavailable, LifecycleError):
            self._safe_stop(binding)
            raise
        except Exception:
            self._safe_stop(binding)
            raise

    @_serialized
    def suspend(self, binding: BrowserBinding) -> OrchestrationResult:
        """Capture current page URLs, then stop the browser cleanly."""
        self._require_transport_owner(binding)
        self._fence_viewer(binding)
        urls = self._transport.list_page_urls()
        captured = self._lifecycle.record_tabs(binding, urls)
        self._transport.stop()
        self._lifecycle.suspend(binding)
        return OrchestrationResult("suspended", self._lifecycle.state, captured.urls)

    @_serialized
    def stop(self, binding: BrowserBinding) -> OrchestrationResult:
        """Stop the browser without accepting a different owner binding."""
        self._require_transport_owner(binding)
        self._fence_viewer(binding)
        self._transport.stop()
        snapshot = self._lifecycle.stop(binding)
        return OrchestrationResult("stopped", snapshot.state)

    @_serialized
    def adopt_binding(self, binding: BrowserBinding) -> OrchestrationResult:
        """Rebind a slot to a new server-minted binding, taking over if needed.

        The new identity is pushed only while the slot is stopped, so one
        generation's downloads can never be attributed to another owner.
        A slot left running by a session that expired or left without
        stopping its runtime is force-stopped here first (self-healing
        takeover, decision 2026-09-08): without it a stale READY lifecycle
        wedges the slot — every control operation then fails closed on the
        foreign binding until a manual container restart (dev01, q-4/q-6).
        """

        if not isinstance(binding, BrowserBinding):
            raise ValueError("binding must be a BrowserBinding")
        current = self._lifecycle.binding
        if binding.browser_id != current.browser_id:
            raise ValueError("binding names a different browser slot")
        self._fence_viewer(current)
        if self._lifecycle.state is not BrowserState.STOPPED:
            # Order matters: stop the browser first, then the lifecycle, so
            # a refused stop leaves the previous owner untouched.
            self._transport.stop()
            self._lifecycle.stop(current)
        push = getattr(self._transport, "push_binding", None)
        if push is not None:
            push(binding)
        try:
            snapshot = self._lifecycle.adopt_binding(binding)
        except LifecycleError as exc:
            raise ValueError(str(exc)) from exc
        return OrchestrationResult("adopted", snapshot.state)

    @_serialized
    def recreate(
        self,
        binding: BrowserBinding,
        *,
        timeout_s: float = 30.0,
        poll_s: float = 0.1,
    ) -> OrchestrationResult:
        """Stop and wake the same binding; never carry state across generations."""
        self.stop(binding)
        return self.wake(binding, timeout_s=timeout_s, poll_s=poll_s)

    def _wait_ready(
        self,
        binding: BrowserBinding,
        *,
        timeout_s: float,
        poll_s: float,
    ) -> BrowserReadiness:
        deadline = self._clock() + timeout_s
        while True:
            readiness = self._transport.readiness()
            if (
                readiness.owner != binding.principal_id
                or readiness.generation != binding.generation
            ):
                raise BrowserOwnershipChanged("browser owner or generation changed")
            if readiness.cdp_ok:
                return readiness
            if self._clock() >= deadline:
                raise ReadinessTimeout("browser readiness deadline exceeded")
            self._sleep(poll_s)

    def _require_transport_owner(self, binding: BrowserBinding) -> None:
        readiness = self._transport.readiness()
        if readiness.owner != binding.principal_id or readiness.generation != binding.generation:
            raise BrowserOwnershipChanged("browser owner or generation changed")

    def _safe_stop(self, binding: BrowserBinding) -> None:
        self._fence_viewer(binding)
        try:
            self._transport.stop()
        finally:
            if self._lifecycle.binding == binding:
                self._lifecycle.stop(binding)

    @staticmethod
    def _require_positive_timeout(timeout_s: float, poll_s: float) -> None:
        if timeout_s <= 0 or poll_s <= 0:
            raise ValueError("timeout_s and poll_s must be positive")
