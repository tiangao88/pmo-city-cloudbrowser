"""Owner-bound authenticated viewer session and restricted HTTP shell."""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping

from cloudbrowser.identity_links import IdentityLinkClient, IdentityLinkClientError
from cloudbrowser.viewer.session_surface import ViewerSessionSurface


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
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CloudBrowser</title>
<style>
:root{color-scheme:light dark}
body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1c1e21}
main{max-width:760px;margin:0 auto;padding:24px}
h1{font-size:20px;margin:0 0 12px}
#panel{background:#fff;border:1px solid #e3e5e8;border-radius:8px;padding:16px;min-height:120px}
button{font:inherit;padding:6px 12px;border-radius:6px;border:1px solid #c9ccd1;background:#fff;cursor:pointer;margin:2px 4px 2px 0}
button:hover{background:#f0f2f4}
input[type=text]{font:inherit;padding:6px 8px;border:1px solid #c9ccd1;border-radius:6px;width:60%}
#status{font-weight:600}
#pageinfo{white-space:pre-wrap;font:12px/1.4 ui-monospace,monospace;background:#f6f7f9;border:1px solid #e3e5e8;border-radius:6px;padding:8px;max-height:200px;overflow:auto}
.err{color:#b3261e}
</style></head>
<body><main>
<h1>CloudBrowser</h1>
<div id="panel">
<p>Session: <span id="status">starting&hellip;</span></p>
<div id="controls" hidden>
<form id="nav"><input type="text" id="url" placeholder="https://example.com" autocomplete="off"><button type="submit">Go</button></form>
<button id="pageinfo">Page info</button><button id="tabs">Tabs</button>
</div>
<div id="pageinfo" hidden></div>
<p id="error" class="err" hidden></p>
</div>
<script>
"use strict";
var st=document.getElementById("status"),err=document.getElementById("error"),
controls=document.getElementById("controls"),out=document.getElementById("pageinfo");
function show(e,m){err.textContent=m;err.hidden=false}
function post(u,body){return fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}).then(function(r){return r.json()})}
function act(op,params){return post("/ui/agent/"+op,{params:params||{}}).then(function(p){
 if(p.status==="ok"){if(p.page){out.textContent=JSON.stringify(p.page,null,1);out.hidden=false}
 if(p.tabs){out.textContent=JSON.stringify(p.tabs,null,1);out.hidden=false}
 }else{show(null,p.error_code||"action failed")}
}).catch(function(){show(null,"action failed")})}
function poll(){fetch("/ui/session").then(function(r){return r.json()}).then(function(p){
 var s=p.status||"failed";
 st.textContent=s;
 if(s==="waiting"){st.textContent="waiting in queue"+(p.position?" (#"+p.position+")":"");setTimeout(poll,2000)}
 else if(s==="offered"){post("/ui/session/activate").then(function(){poll()})}
 else if(s==="active"){controls.hidden=false;st.textContent="active"+(p.session_ttl_s?" \u00b7 "+Math.round(p.session_ttl_s/60)+" min left":"")}
 else if(s==="failed"){show(null,p.error_code||"session failed")}
 else{setTimeout(poll,3000)}
}).catch(function(){st.textContent="offline";setTimeout(poll,3000)})}
post("/ui/session/join").then(poll).catch(function(){st.textContent="offline"});
document.getElementById("nav").addEventListener("submit",function(e){e.preventDefault();
 var u=document.getElementById("url").value.trim();if(!u)return;
 if(!/^https:\\/\\//.test(u))u="https://"+u;act("navigate",{url:u})});
document.getElementById("pageinfo").addEventListener("click",function(){act("page_info")});
document.getElementById("tabs").addEventListener("click",function(){act("tabs_list")});
</script></main></body></html>"""


def create_viewer_server(
    viewer: AuthenticatedViewer | None,
    *,
    address: tuple[str, int] = ("127.0.0.1", 8082),
    allow_edge_identity: bool = False,
    session_surface: ViewerSessionSurface | None = None,
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

    if session_surface is not None and allow_edge_identity is not True:
        raise ValueError("session_surface requires the authenticated edge mode")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if self.path == "/health":
                self._json(200, {"status": "ok", "component": "viewer"})
                return
            if session_surface is not None and self.path == "/ui/session":
                self._surface_call("status")
                return
            if self.path not in ("/", "/viewer"):
                self.send_error(404)
                return
            token = _bearer(self.headers.get("Authorization"))
            token_valid = viewer is not None and viewer._store.get(token) is not None
            if not token_valid and not self._edge_authenticated():
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
            if viewer is not None and isinstance(viewer.identity_client, IdentityLinkClient):
                from cloudbrowser.edge_auth import parse_edge_identity

                identity = parse_edge_identity(dict(self.headers.items()))
                resolver = viewer.identity_client
                if identity is None:
                    return False
                try:
                    return resolver.resolve(identity) is not None
                except IdentityLinkClientError:
                    return False
            # Surface-only configuration: authorize the shell through the
            # session surface's own fail-closed identity resolution so the
            # UI and its data routes share exactly one identity rule.
            if session_surface is not None:
                try:
                    return session_surface.status(
                        headers=dict(self.headers.items()),
                        request_id="shell-" + secrets.token_urlsafe(8),
                    )[1].get("error_code") != "unauthorized"
                except Exception:
                    return False
            return False

        def _surface_call(self, action: str) -> None:
            """Run one session-surface action for the edge-authenticated caller."""
            assert session_surface is not None
            request_id = self.headers.get("X-CB-Request-Id") or "ui-" + secrets.token_urlsafe(8)
            if not isinstance(request_id, str) or len(request_id) > 128:
                self._json(
                    200,
                    {"ok": False, "request_id": "", "status": "failed", "error_code": "invalid_request"},
                )
                return
            try:
                if action == "status":
                    status, payload = session_surface.status(
                        headers=dict(self.headers.items()), request_id=request_id
                    )
                elif action == "join":
                    status, payload = session_surface.join(
                        headers=dict(self.headers.items()), request_id=request_id
                    )
                else:
                    status, payload = session_surface.activate(
                        headers=dict(self.headers.items()), request_id=request_id
                    )
            except Exception:
                self._json(
                    200,
                    {"ok": False, "request_id": request_id, "status": "failed", "error_code": "surface_failed"},
                )
                return
            self._json(status, payload)

        def _agent_call(self, operation: str) -> None:
            """Relay one allowlisted page action for the edge-authenticated caller."""
            assert session_surface is not None
            request_id = self.headers.get("X-CB-Request-Id") or "ui-" + secrets.token_urlsafe(8)
            if not isinstance(request_id, str) or len(request_id) > 128:
                self._json(
                    200,
                    {"ok": False, "request_id": "", "status": "failed", "error_code": "invalid_request"},
                )
                return
            if not isinstance(operation, str) or not operation or len(operation) > 64:
                self._json(
                    200,
                    {"ok": False, "request_id": request_id, "status": "failed", "error_code": "operation_not_supported"},
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 8192:
                    raise ValueError
                raw = json.loads(self.rfile.read(length))
                if not isinstance(raw, dict):
                    raise ValueError
                params = raw.get("params", {})
                if not isinstance(params, dict):
                    raise ValueError
            except (ValueError, TypeError, json.JSONDecodeError):
                self._json(
                    200,
                    {"ok": False, "request_id": request_id, "status": "failed", "error_code": "invalid_request"},
                )
                return
            try:
                status, payload = session_surface.agent(
                    operation,
                    headers=dict(self.headers.items()),
                    params=params,
                    request_id=request_id,
                )
            except Exception:
                self._json(
                    200,
                    {"ok": False, "request_id": request_id, "status": "failed", "error_code": "surface_failed"},
                )
                return
            self._json(status, payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            if session_surface is not None and self.path == "/ui/session/join":
                self._surface_call("join")
                return
            if session_surface is not None and self.path == "/ui/session/activate":
                self._surface_call("activate")
                return
            if session_surface is not None and self.path.startswith("/ui/agent/"):
                self._agent_call(self.path[len("/ui/agent/") :])
                return
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
