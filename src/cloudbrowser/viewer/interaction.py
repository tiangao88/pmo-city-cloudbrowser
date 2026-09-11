"""Shared browser/viewer control gate for the integrated desktop candidate."""
import threading
import time


class InteractionGate:
    def __init__(self, *, clock=time.monotonic, broker_jobs=None):
        self.lock = threading.RLock()
        self.clock = clock
        self.mode = "paused"
        self.controller = None
        self.changed_at = clock()
        self.broker_jobs = broker_jobs

    def change(self, mode, controller=None):
        if mode not in ("paused", "initializing", "agent", "human"):
            raise ValueError("invalid interaction mode")
        with self.lock:
            # Local browser access fails closed even if shared state I/O fails.
            if self.broker_jobs is not None:
                self.mode, self.controller = "paused", None
                self.changed_at = self.clock()
                self.broker_jobs.change(mode if mode in ("agent", "human") else "paused")
            self.mode, self.controller = mode, controller
            self.changed_at = self.clock()

    def permits_browser(self, path, received):
        # Health/lifecycle must remain reachable to stop or replace a browser.
        if path in ("/browser/health", "/browser/readiness", "/browser/start", "/browser/stop", "/browser/binding", "/browser/pages"):
            # The private supervisor snapshots URLs after fencing. Agent reads
            # use /agent/* and remain blocked; this is not a public endpoint.
            return True
        if path.startswith("/browser/pages") and self.mode == "initializing":
            return received >= self.changed_at
        return self.mode == "agent" and received >= self.changed_at

    def permits_viewer(self, token):
        return self.mode != "human" or token == self.controller
