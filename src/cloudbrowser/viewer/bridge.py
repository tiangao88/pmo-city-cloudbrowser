"""In-memory owner-bound browser stream registry for the viewer boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

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
    """Authorize a viewer session against a server-owned readiness binding."""

    def __init__(
        self,
        *,
        readiness: Callable[[], BrowserReadiness],
        stream_endpoint: str,
    ) -> None:
        if not isinstance(stream_endpoint, str) or not stream_endpoint.startswith("/"):
            raise ValueError("stream_endpoint must be an internal relative path")
        if ".." in stream_endpoint or "//" in stream_endpoint:
            raise ValueError("stream_endpoint must not escape the viewer origin")
        self._readiness = readiness
        self._stream_endpoint = stream_endpoint

    def open_stream(self, session: ViewerSession, request: ViewerRequest) -> BrowserStream:
        if session.public_dict()["request_id"] != request.request_id:
            raise PermissionError("viewer binding mismatch")
        ready = self._readiness()
        expected = (session.profile_id, session.principal_id, session.browser_id, session.generation)
        actual = (request.profile_id, request.principal_id, request.browser_id, request.generation)
        observed = (ready.owner, ready.generation)
        if expected != actual or observed != (session.principal_id, session.generation):
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
