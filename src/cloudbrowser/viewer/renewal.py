"""Opt-in supervisor heartbeat worker. Never fences or enables automatically."""
import math
import threading

from .fence_control import ViewerFenceClient


class ViewerRenewalWorker:
    def __init__(self, renew, *, interval_s=3):
        if not isinstance(interval_s, (int, float)) or not math.isfinite(interval_s) or not 0 < interval_s <= 5:
            raise ValueError("renewal interval must be between zero and five seconds")
        self._renew = renew
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread = None
        self.last_outcome = "idle"

    def tick(self):
        if self._stop.is_set():
            return
        try:
            self.last_outcome = "renewed" if self._renew() else "skipped"
        except Exception:
            # Bounded diagnostic only: never capture exceptions, cookies or
            # bindings. Failure does not fence/enable or revive an expired lease.
            self.last_outcome = "unavailable"

    def _run(self):
        while not self._stop.wait(self._interval):
            self.tick()

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise RuntimeError("renewal worker cannot be restarted")
        self._thread = threading.Thread(target=self._run, name="viewer-renewal", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_s=15):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            if self._thread.is_alive():
                raise RuntimeError("viewer renewal worker did not stop")


def configured_viewer_client(environ):
    """Deliberately absent from release Compose; explicit experiment opt-in."""
    enabled = environ.get("CB_EXPERIMENTAL_VIEWER_CONTROL", "0")
    url = environ.get("CB_VIEWER_CONTROL_URL")
    secret = environ.get("CB_VIEWER_CONTROL_SECRET")
    if enabled not in ("0", "1"):
        raise ValueError("invalid experimental viewer control flag")
    if enabled == "0":
        if url or secret:
            raise ValueError("viewer control settings require explicit experiment opt-in")
        return None
    if not url or not secret:
        raise ValueError("experimental viewer control requires URL and dedicated secret")
    return ViewerFenceClient(base_url=url, shared_secret=secret)
