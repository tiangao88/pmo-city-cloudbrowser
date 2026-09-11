"""Restart-scoped fence/enable handshake for one private slot authority.

The random ticket lives only in this process. Restart or a new fence invalidates
old tickets. All control-plane changes must go through this coordinator.
"""
import secrets
from threading import RLock

from . import ViewerRequest


class ViewerTransition:
    def __init__(self, authority, *, reset_display=None):
        self._authority = authority
        self._reset_display = reset_display
        self._lock = RLock()
        self._ticket = None
        self._browser_id = None
        self._enabled = None

    def fence(self, binding):
        with self._lock:
            self._ticket = None
            self._enabled = None
            self._authority.fence(binding)
            self._browser_id = binding.browser_id
            self._ticket = secrets.token_hex(32)
            return self._ticket

    def enable(self, ticket, binding):
        with self._lock:
            if (not isinstance(ticket, str) or not self._ticket
                    or not secrets.compare_digest(ticket, self._ticket)
                    or self._reset_display is None or binding.browser_id != self._browser_id):
                raise PermissionError("viewer enable unavailable")
            if self._enabled is not None:
                if self._enabled != binding:
                    raise PermissionError("viewer enable mismatch")
                return  # Exact retry after a lost acknowledgement.
            request = ViewerRequest(secrets.token_hex(32), binding.profile_id,
                binding.principal_id, binding.browser_id, binding.generation)
            try:
                self._authority.publish_fenced(request, reset_display=self._reset_display)
            except Exception:
                self._ticket = None  # Unknown cleanup outcome requires a new fence.
                raise
            self._enabled = binding
