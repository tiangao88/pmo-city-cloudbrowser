"""Transport-independent live-view lifecycle; not yet wired to WebSockets.

The transport must call forward_frame for every outbound frame, poll while
idle, and revoke before changing a slot binding. Raw VNC client input must
not be forwarded: this first increment is observation-only.
"""

from __future__ import annotations

from threading import RLock
from typing import Callable

from . import AuthenticatedViewer, ViewerRequest
from .bridge import ViewerBrowserBridge


class LiveViewConnection:
    """Recheck current server authority rather than retaining admission alone.

    Callbacks must be bounded and synchronous. Slot lifecycle integration must
    serialize rebind with revoke; polling alone cannot make rebind atomic.
    No token, frame or backend endpoint is exposed by this object's repr.
    """

    def __init__(
        self,
        *,
        viewer: AuthenticatedViewer,
        bridge: ViewerBrowserBridge,
        token: str,
        current_request: Callable[[], ViewerRequest],
        send_frame: Callable[[bytes], None],
        close_transport: Callable[[], None],
    ) -> None:
        self._viewer = viewer
        self._bridge = bridge
        self._token = token
        self._current_request = current_request
        self._send_frame = send_frame
        self._close_transport = close_transport
        self._lock = RLock()
        self._closed = False
        if not self.poll():
            raise PermissionError("live viewer unavailable")

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _check(self) -> bool:
        if self._closed:
            return False
        try:
            request = self._current_request()
            session = self._viewer.authorize(self._token, request)
            self._bridge.open_stream(session, request)
        except Exception:
            self.revoke()
            return False
        return True

    def poll(self) -> bool:
        """Transport timer checks expiry/revocation even on a static display."""
        with self._lock:
            return self._check()

    def forward_frame(self, frame: bytes) -> bool:
        with self._lock:
            if not self._check():
                return False
            try:
                self._send_frame(frame)
            except Exception:
                self.revoke()
                return False
            return True

    def revoke(self) -> None:
        """Fence subsequent writes before asking the transport to close."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._token = ""
            self._close_transport()
