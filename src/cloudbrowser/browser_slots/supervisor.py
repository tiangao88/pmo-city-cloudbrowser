"""Owner-bound slot supervisor orchestration."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

from .lifecycle import BrowserBinding, BrowserState, LifecycleError, OwnerBoundLifecycle
from .transport import BrowserOwnershipChanged, BrowserReadiness, BrowserTransport, BrowserUnavailable


class ReadinessTimeout(BrowserUnavailable):
    """Raised when a started browser never becomes ready within the deadline."""


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
    ) -> None:
        self._lifecycle = lifecycle
        self._transport = transport
        self._clock = clock
        self._sleep = sleep

    @property
    def lifecycle(self) -> OwnerBoundLifecycle:
        return self._lifecycle

    def wake(
        self,
        binding: BrowserBinding,
        *,
        timeout_s: float = 30.0,
        poll_s: float = 0.1,
    ) -> OrchestrationResult:
        """Start the browser, wait for matching readiness, and restore tabs."""
        self._require_positive_timeout(timeout_s, poll_s)
        self._lifecycle.start(binding)
        try:
            self._transport.start()
            self._wait_ready(binding, timeout_s=timeout_s, poll_s=poll_s)
            self._lifecycle.mark_ready(binding)
            urls = self._lifecycle.load_tabs(binding)
            for url in urls:
                self._transport.open_page(url)
            self._transport.close_empty_pages()
            return OrchestrationResult("ready", self._lifecycle.state, urls)
        except (BrowserOwnershipChanged, BrowserUnavailable, LifecycleError):
            self._safe_stop(binding)
            raise
        except Exception:
            self._safe_stop(binding)
            raise

    def suspend(self, binding: BrowserBinding) -> OrchestrationResult:
        """Capture current page URLs, then stop the browser cleanly."""
        self._require_transport_owner(binding)
        urls = self._transport.list_page_urls()
        captured = self._lifecycle.record_tabs(binding, urls)
        self._transport.stop()
        self._lifecycle.suspend(binding)
        return OrchestrationResult("suspended", self._lifecycle.state, captured.urls)

    def stop(self, binding: BrowserBinding) -> OrchestrationResult:
        """Stop the browser without accepting a different owner binding."""
        self._require_transport_owner(binding)
        self._transport.stop()
        snapshot = self._lifecycle.stop(binding)
        return OrchestrationResult("stopped", snapshot.state)

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
            if readiness.owner != binding.principal_id or readiness.generation != binding.generation:
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
        try:
            self._transport.stop()
        finally:
            if self._lifecycle.binding == binding:
                self._lifecycle.stop(binding)

    @staticmethod
    def _require_positive_timeout(timeout_s: float, poll_s: float) -> None:
        if timeout_s <= 0 or poll_s <= 0:
            raise ValueError("timeout_s and poll_s must be positive")
