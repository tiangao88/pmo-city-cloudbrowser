"""In-memory owner-bound browser stream registry for the viewer boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..browser_slots.lifecycle import BrowserBinding
from ..browser_slots.transport import BrowserReadiness, BrowserUnavailable
from . import ViewerRequest, ViewerSession


@dataclass(frozen=True)
class BrowserStream:
    """Opaque stream descriptor; transport-specific URLs never enter the agent API."""

    session_token: str
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str
    endpoint: str

    def public_dict(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "principal_id": self.principal_id,
            "browser_id": self.browser_id,
            "generation": self.generation,
            "endpoint": self.endpoint,
        }


class ViewerBrowserBridge:
    """Authorize a viewer session against the server-derived binding and readiness.

    ``binding`` pins this bridge to the router-assigned ``BrowserBinding`` of
    the slot browser the viewer serves. When pinned, a session whose binding
    tuple differs from the server binding is denied even if the caller's
    request and readiness claims are internally consistent, so the opened
    stream can never describe a browser the server did not assign.
    """

    def __init__(
        self,
        *,
        readiness: Callable[[], BrowserReadiness],
        stream_endpoint: str,
        binding: BrowserBinding | None = None,
    ) -> None:
        if not isinstance(stream_endpoint, str) or not stream_endpoint.startswith("/"):
            raise ValueError("stream_endpoint must be an internal relative path")
        if ".." in stream_endpoint or "//" in stream_endpoint:
            raise ValueError("stream_endpoint must not escape the viewer origin")
        if binding is not None and not isinstance(binding, BrowserBinding):
            raise TypeError("binding must be a BrowserBinding")
        self._readiness = readiness
        self._stream_endpoint = stream_endpoint
        self._binding = binding

    def open_stream(self, session: ViewerSession, request: ViewerRequest) -> BrowserStream:
        if session.public_dict()["request_id"] != request.request_id:
            raise PermissionError("viewer binding mismatch")
        expected = (session.profile_id, session.principal_id, session.browser_id, session.generation)
        actual = (request.profile_id, request.principal_id, request.browser_id, request.generation)
        if expected != actual:
            raise PermissionError("viewer binding mismatch")
        if self._binding is not None:
            bound = (
                self._binding.profile_id,
                self._binding.principal_id,
                self._binding.browser_id,
                self._binding.generation,
            )
            if expected != bound:
                raise PermissionError("viewer binding mismatch")
        ready = self._readiness()
        if (ready.owner, ready.generation) != (session.principal_id, session.generation):
            raise PermissionError("viewer binding mismatch")
        if not ready.cdp_ok:
            raise BrowserUnavailable("browser is not ready")
        return BrowserStream(
            session_token=session.token,
            profile_id=session.profile_id,
            principal_id=session.principal_id,
            browser_id=session.browser_id,
            generation=session.generation,
            endpoint=self._stream_endpoint,
        )


__all__ = ["BrowserStream", "ViewerBrowserBridge"]
