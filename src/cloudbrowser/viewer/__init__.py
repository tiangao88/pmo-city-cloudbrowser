"""Owner-bound authenticated viewer session and restricted HTTP shell."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from typing import Callable, Mapping

from cloudbrowser.identity_links import IdentityLinkClient, IdentityLinkClientError


@dataclass(frozen=True)
class ViewerRequest:
    """Server-derived identity needed to open one viewer session."""

    request_id: str
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str

    def __post_init__(self) -> None:
        for field in ("request_id", "profile_id", "principal_id", "browser_id", "generation"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(f"{field} must be bounded non-empty text")


@dataclass(frozen=True)
class ViewerSession:
    """Opaque session token plus non-sensitive owner binding metadata."""

    request_id: str
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str
    expires_at: float
    token: str

    def public_dict(self) -> Mapping[str, str | float]:
        return {
            "request_id": self.request_id,
            "profile_id": self.profile_id,
            "principal_id": self.principal_id,
            "browser_id": self.browser_id,
            "generation": self.generation,
            "expires_at": self.expires_at,
        }


class ViewerSessionStore:
    """Thread-safe in-memory expiring session store."""

    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._sessions: dict[str, ViewerSession] = {}
        self._revoked: set[str] = set()
        self._lock = threading.RLock()

    def put(self, session: ViewerSession) -> None:
        with self._lock:
            self._sessions[session.token] = session

    def get(self, token: str) -> ViewerSession | None:
        with self._lock:
            if not isinstance(token, str) or not token or token in self._revoked:
                return None
            session = self._sessions.get(token)
            if session is None or self._clock() >= session.expires_at:
                return None
            return session

    def revoke(self, token: str) -> None:
        if isinstance(token, str) and token:
            with self._lock:
                self._revoked.add(token)
                self._sessions.pop(token, None)

    def clock(self) -> float:
        return self._clock()


class AuthenticatedViewer:
    """Issue and validate owner-bound viewer sessions without browser secrets."""

    def __init__(
        self,
        store: ViewerSessionStore,
        *,
        token_secret: bytes,
        ttl_s: float = 360.0,
        token_factory: Callable[[], str] | None = None,
        identity_client=None,
    ) -> None:
        if not isinstance(token_secret, bytes) or len(token_secret) < 16:
            raise ValueError("token_secret must be at least 16 bytes")
        if not isinstance(ttl_s, (int, float)) or ttl_s <= 0 or ttl_s > 3600:
            raise ValueError("ttl_s must be positive and bounded")
        self._store = store
        self._ttl_s = float(ttl_s)
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self.identity_client = identity_client

    def open_session(self, request: ViewerRequest) -> ViewerSession:
        token = self._token_factory()
        if not isinstance(token, str) or not token or len(token) > 256:
            raise ValueError("token factory returned invalid token")
        session = ViewerSession(
            request_id=request.request_id,
            profile_id=request.profile_id,
            principal_id=request.principal_id,
            browser_id=request.browser_id,
            generation=request.generation,
            expires_at=self._store.clock() + self._ttl_s,
            token=token,
        )
        self._store.put(session)
        return session

    def authorize(self, token: str, request: ViewerRequest) -> ViewerSession:
        if not isinstance(token, str) or not token:
            raise PermissionError("viewer token required")
        session = self._store.get(token)
        if session is None:
            raise PermissionError("viewer session unavailable")
        expected = (
            request.request_id,
            request.profile_id,
            request.principal_id,
            request.browser_id,
            request.generation,
        )
        actual = (
            session.request_id,
            session.profile_id,
            session.principal_id,
            session.browser_id,
            session.generation,
        )
        if actual != expected:
            raise PermissionError("viewer binding mismatch")
        return session


_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CloudBrowser</title></head>
<body><main><h1>CloudBrowser</h1><p>Viewer is ready. No interactive browser surface is attached to this instance.</p></main></body></html>"""


def create_viewer_server(
    viewer: AuthenticatedViewer,
    *,
    address: tuple[str, int] = ("127.0.0.1", 8082),
    allow_edge_identity: bool = False,
) -> ThreadingHTTPServer:
    """Create the authenticated viewer shell; no CDP or profile routes exist.

    ``allow_edge_identity`` opts the deployment into trusting the
    Traefik/TinyAuth forward-auth identity headers (``remote-email`` etc.)
    that are only present after the edge authenticated the employee. When
    enabled, ``GET /`` and ``GET /viewer`` are served to an authenticated
    employee without requiring a separately issued bearer viewer token.
    The flag must only be set when the host is behind the authenticated
    proxy (``CB_EDGE_AUTH=traefik-forwardauth``).
    """

    if not isinstance(allow_edge_identity, bool):
        raise TypeError("allow_edge_identity must be a bool")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path == "/health":
                self._json(200, {"status": "ok", "component": "viewer"})
                return
            if self.path not in ("/", "/viewer"):
                self.send_error(404)
                return
            token = _bearer(self.headers.get("Authorization"))
            if viewer._store.get(token) is None and not self._edge_authenticated():
                self.send_error(401)
                return
            body = _SHELL.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _edge_authenticated(self) -> bool:
            if not allow_edge_identity:
                return False
            from cloudbrowser.edge_auth import parse_edge_identity

            identity = parse_edge_identity(dict(self.headers.items()))
            resolver = viewer.identity_client
            if identity is None or not isinstance(resolver, IdentityLinkClient):
                return False
            try:
                return resolver.resolve(identity) is not None
            except IdentityLinkClientError:
                return False

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path != "/viewer/session":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096:
                    raise ValueError
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError
                token = raw.get("token")
                values = [raw.get(key) for key in ("request_id", "profile_id", "principal_id", "browser_id", "generation")]
                if any(not isinstance(value, str) for value in values):
                    raise ValueError
                request = ViewerRequest(*values)
                session = viewer.authorize(token, request)
            except PermissionError:
                self._json(403, {"ok": False, "error_code": "viewer_forbidden"})
                return
            except (ValueError, TypeError, json.JSONDecodeError):
                self._json(400, {"ok": False, "error_code": "invalid_request"})
                return
            self._json(200, {"ok": True, "session": dict(session.public_dict())})

        def _json(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    return ThreadingHTTPServer(address, Handler)


def _bearer(value: str | None) -> str:
    if not isinstance(value, str) or not value.startswith("Bearer "):
        return ""
    token = value[7:]
    return token if token and len(token) <= 256 and " " not in token else ""


__all__ = [
    "AuthenticatedViewer",
    "ViewerRequest",
    "ViewerSession",
    "ViewerSessionStore",
    "create_viewer_server",
]
