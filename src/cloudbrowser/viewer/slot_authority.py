"""Single-process viewer admission and slot-transition coordinator.

Internal integration seam, not an HTTP endpoint. Edge headers must come from
the authenticated, header-sanitizing gateway. Only the trusted slot lifecycle
may call rebind. This lock cannot coordinate independent service processes.
"""
from threading import RLock

from cloudbrowser.edge_auth import REQUIRED_GROUP, parse_edge_identity
from . import ViewerRequest
from .bridge import ViewerBrowserBridge
from .live_connection import LiveViewConnection


class SlotViewerAuthority:
    def __init__(self, *, viewer, identity_client, readiness, stream_endpoint):
        self._viewer = viewer
        self._identity = identity_client
        self._readiness = readiness
        self._endpoint = stream_endpoint
        self._lock = RLock()
        self._binding = None
        self._used_generations = set()
        self._connections = set()
        self._teardown_failed = False

    def _current(self):
        if self._binding is None:
            raise PermissionError("viewer unavailable")
        return self._binding

    def _principal(self, headers):
        identity = parse_edge_identity(headers)
        if identity is None or REQUIRED_GROUP not in identity.groups:
            raise PermissionError("viewer unavailable")
        try:
            principal = self._identity.resolve(identity)
        except Exception:
            raise PermissionError("viewer unavailable") from None
        if not isinstance(principal, str) or principal != self._current().principal_id:
            raise PermissionError("viewer unavailable")

    def issue(self, *, trusted_headers):
        """No caller-supplied profile, principal, browser or generation fields."""
        with self._lock:
            self._principal(trusted_headers)
            return self._viewer.open_session(self._current())

    def connect(self, *, trusted_headers, token, send_frame, close_transport):
        with self._lock:
            self._principal(trusted_headers)
            self._connections = {c for c in self._connections if not c.closed}
            def close():
                try:
                    close_transport()
                except Exception:
                    self._teardown_failed = True
                    self._binding = None
                    raise
            connection = LiveViewConnection(
                viewer=self._viewer,
                bridge=ViewerBrowserBridge(readiness=self._readiness, stream_endpoint=self._endpoint),
                token=token, current_request=self._current, send_frame=send_frame,
                close_transport=close, lifecycle_lock=self._lock,
            )
            self._connections.add(connection)
            return connection

    def rebind(self, binding: ViewerRequest | None, *, apply_binding):
        """Close old transports before changing the browser, under one lock.

        Callbacks must finish synchronously with bounded I/O. A close/apply
        failure leaves admission unavailable. apply_binding must clear old
        browser/display state; it must not reenter this coordinator.
        """
        with self._lock:
            if self._teardown_failed:
                raise RuntimeError("viewer transport teardown failed")
            if binding is not None:
                if not isinstance(binding, ViewerRequest):
                    raise TypeError("invalid viewer binding")
                if binding.generation in self._used_generations:
                    raise ValueError("viewer generation must be fresh")
                self._used_generations.add(binding.generation)
            self._binding = None
            failed = False
            for connection in self._connections:
                try:
                    connection.revoke()
                except Exception:
                    failed = True
            self._connections.clear()
            if failed:
                self._teardown_failed = True
                raise RuntimeError("viewer transport teardown failed")
            apply_binding()
            self._binding = binding
