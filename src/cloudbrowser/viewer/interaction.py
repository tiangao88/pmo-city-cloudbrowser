"""Shared browser/viewer control gate for the integrated desktop candidate."""
import threading
import time


class InteractionGate:
    def __init__(self, *, clock=time.monotonic):
        self.lock = threading.RLock()
        self.clock = clock
        self.mode = "paused"
        self.controller = None
        self.changed_at = clock()

    def change(self, mode, controller=None):
        if mode not in ("paused", "initializing", "agent", "human"):
            raise ValueError("invalid interaction mode")
        with self.lock:
            self.mode, self.controller = mode, controller
            self.changed_at = self.clock()

    def permits_browser(self, path, received):
        # Health/lifecycle must remain reachable to stop or replace a browser.
        if path in ("/browser/health", "/browser/readiness", "/browser/start", "/browser/stop", "/browser/binding"):
            return True
        if path.startswith("/browser/pages") and self.mode == "initializing":
            return received >= self.changed_at
        return self.mode == "agent" and received >= self.changed_at

    def permits_viewer(self, token):
        return self.mode != "human" or token == self.controller
