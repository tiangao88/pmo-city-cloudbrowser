"""Single-process viewer admission and slot-transition coordinator.

Internal integration seam, not an HTTP endpoint. Edge headers must come from
the authenticated, header-sanitizing gateway. Only the trusted slot lifecycle
may call rebind. This lock cannot coordinate independent service processes.
"""
from threading import RLock
import time
import math

from cloudbrowser.edge_auth import REQUIRED_GROUP, parse_edge_identity
from . import ViewerRequest
from .bridge import ViewerBrowserBridge
from .live_connection import LiveViewConnection
from cloudbrowser.broker_jobs import JobsUnavailable


class SlotViewerAuthority:
    def __init__(self, *, viewer, identity_client, readiness, stream_endpoint, clock=time.monotonic,
                 interaction_gate=None, set_input=None):
        self._viewer = viewer
        self._identity = identity_client
        self._readiness = readiness
        self._endpoint = stream_endpoint
        self._interaction = interaction_gate
        self._set_input = set_input
        if interaction_gate is not None and set_input is None:
            raise ValueError("interaction requires a server-side input controller")
        self._lock = interaction_gate.lock if interaction_gate is not None else RLock()
        self._binding = None
        self._used_generations = set()
        self._connections = set()
        self._teardown_failed = False
        self._clock = clock
        self._lease_deadline = None

    def _current(self):
        self._expire_lease()
        if self._binding is None:
            raise PermissionError("viewer unavailable")
        return self._binding

    def _expire_lease(self):
        if self._lease_deadline is not None and self._clock() >= self._lease_deadline:
            self.rebind(None, apply_binding=lambda: None)

    def poll_lease(self):
        """Called by the service timer even when no viewer is connected."""
        with self._lock:
            self._expire_lease()

    def require_lease(self, epoch):
        with self._lock:
            if self._current().request_id != epoch or self._lease_deadline is None:
                raise PermissionError("viewer lease unavailable")

    def renew_lease(self, epoch, *, lease_s):
        with self._lock:
            self.require_lease(epoch)
            self._validate_lease(lease_s)
            self._lease_deadline = self._clock() + lease_s

    @staticmethod
    def _validate_lease(lease_s):
        if not isinstance(lease_s, (int, float)) or not math.isfinite(lease_s) or not 0 < lease_s <= 60:
            raise ValueError("lease duration must be finite and bounded")

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

    def issue_leased(self, *, trusted_headers):
        """Public issuer seam: only a control-enabled, ready binding qualifies."""
        with self._lock:
            self._principal(trusted_headers)
            binding = self._current()
            self.require_lease(binding.request_id)
            ready = self._readiness()
            if (ready.owner, ready.generation, ready.cdp_ok) != (
                binding.principal_id, binding.generation, True
            ):
                raise PermissionError("viewer unavailable")
            return self._viewer.open_session(binding)

    def connect(self, *, trusted_headers, token, send_frame, close_transport):
        with self._lock:
            self._principal(trusted_headers)
            self._connections = {c for c in self._connections if not c.closed}
            if self._interaction is not None and (
                not self._interaction.permits_viewer(token)
                or (self._interaction.mode == "human" and self._connections)
            ):
                raise PermissionError("viewer control unavailable")
            def close():
                try:
                    close_transport()
                    if (self._interaction is not None and self._interaction.mode == "human"
                            and self._interaction.controller == token):
                        self._interaction.change("paused")
                        self._set_input(False)
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

    def authorize_stream(self, *, trusted_headers, token):
        """Upgrade preflight; connect and every write must still reauthorize."""
        with self._lock:
            self._principal(trusted_headers)
            if self._interaction is not None and not self._interaction.permits_viewer(token):
                raise PermissionError("viewer control unavailable")
            binding = self._current()
            self.require_lease(binding.request_id)
            session = self._viewer.authorize(token, binding)
            ViewerBrowserBridge(readiness=self._readiness, stream_endpoint=self._endpoint).open_stream(session, binding)

    def control(self, action, *, trusted_headers, token):
        with self._lock:
            if self._interaction is None:
                raise PermissionError("viewer control unavailable")
            self.authorize_stream(trusted_headers=trusted_headers, token=token)
            if action == "status":
                return self._interaction.mode
            if action not in ("takeover", "resume"):
                raise ValueError("unknown viewer control action")
            self._interaction.change("paused")
            try:
                for connection in self._connections:
                    connection.revoke()
                self._connections.clear()
                self._set_input(False)
                self._interaction.change("human" if action == "takeover" else "agent",
                    token if action == "takeover" else None)
                self._set_input(action == "takeover")
            except JobsUnavailable:
                # Pending jobs retain their exclusion until they actually exit.
                # Leave paused/input-off and allow an explicit control retry.
                raise
            except Exception:
                self._interaction.change("paused")
                self._teardown_failed = True
                self._binding = None
                raise
            return self._interaction.mode

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
            self._lease_deadline = None
            if self._interaction is not None:
                self._interaction.change("paused")
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
            if self._interaction is not None:
                try:
                    self._set_input(False)
                except Exception:
                    self._teardown_failed = True
                    raise
            apply_binding()
            self._binding = binding

    def fence(self, expected):
        """Private control-plane operation: acknowledge only after teardown.

        Retries while already fenced are harmless. A stale request must never
        fence a different, newly admitted binding.
        """
        with self._lock:
            if self._binding is not None:
                for field in ("profile_id", "principal_id", "browser_id", "generation"):
                    if getattr(self._binding, field) != getattr(expected, field):
                        raise PermissionError("viewer binding mismatch")
            self.rebind(None, apply_binding=lambda: None)

    def publish_fenced(self, binding: ViewerRequest, *, reset_display, lease_s=15):
        """Internal enable seam: fresh session epoch after confirmed teardown.

        A resumed browser may retain its generation, but request_id must be a
        fresh control-plane epoch so pre-fence cookies never regain authority.
        Caller must serialize this with fencing and never reuse an epoch.
        """
        with self._lock:
            self._validate_lease(lease_s)
            if self._binding is not None or self._teardown_failed:
                raise PermissionError("viewer is not fenced")
            reset_display()
            ready = self._readiness()
            if (ready.owner, ready.generation, ready.cdp_ok) != (
                binding.principal_id, binding.generation, True
            ):
                raise PermissionError("viewer browser not ready")
            self._binding = binding
            self._lease_deadline = self._clock() + lease_s
            if self._interaction is not None:
                try:
                    self._interaction.change("agent")
                except Exception:
                    self._binding = None
                    self._lease_deadline = None
                    raise
