"""Private, opt-in viewer fencing RPC. Not exposed by the deployed runtime.

Fencing disables authority; enabling read-only admission additionally requires
a restart-scoped ticket, readiness and an explicit display-reset callback.
Never enables human input. Requires a private authenticated service network.
"""
import hmac
import http.client
import json
import secrets
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.transport import BrowserUnavailable
from .transition import ViewerTransition

PATH = "/internal/viewer/fence"
ENABLE_PATH = "/internal/viewer/enable"


def create_fence_server(authority, *, shared_secret, address=("127.0.0.1", 0), reset_display=None):
    if not isinstance(shared_secret, str) or len(shared_secret) < 32:
        raise ValueError("fence secret must contain at least 32 characters")
    transition = ViewerTransition(authority, reset_display=reset_display)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path not in (PATH, ENABLE_PATH) or not hmac.compare_digest(
                self.headers.get("Authorization", ""), "Bearer " + shared_secret
            ):
                self.send_error(403)
                return
            self.connection.settimeout(2)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                    raise ValueError()
                body = json.loads(self.rfile.read(length))
                nonce = body["nonce"]
                raw = body["binding"]
                if not isinstance(nonce, str) or len(nonce) != 32:
                    raise ValueError()
                if set(raw) != {"profile_id", "principal_id", "browser_id", "generation"}:
                    raise ValueError()
                if any(not isinstance(v, str) or not v or len(v) > 256 for v in raw.values()):
                    raise ValueError()
                binding = BrowserBinding(**raw)
                if self.path == PATH:
                    ticket = transition.fence(binding)
                    result = {"fenced": True, "nonce": nonce, "ticket": ticket}
                else:
                    transition.enable(body.get("ticket"), binding)
                    result = {"enabled": True, "nonce": nonce}
            except Exception:
                self.send_error(409, "Viewer fence unavailable")
                return
            payload = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(address, Handler)


class ViewerFenceClient:
    def __init__(self, *, base_url, shared_secret, timeout_s=2):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError("fence endpoint must be a service origin")
        if not isinstance(shared_secret, str) or len(shared_secret) < 32 or not 0 < timeout_s <= 10:
            raise ValueError("invalid fence client configuration")
        self._origin, self._secret, self._timeout = parsed, shared_secret, timeout_s
        self._ticket = None

    def __call__(self, binding):
        self._ticket = None
        self._ticket = self._call(PATH, binding)

    def enable(self, binding):
        if self._ticket is None:
            raise BrowserUnavailable("viewer fence required")
        self._call(ENABLE_PATH, binding, ticket=self._ticket)

    def _call(self, path, binding, *, ticket=None):
        nonce = secrets.token_hex(16)
        cls = http.client.HTTPSConnection if self._origin.scheme == "https" else http.client.HTTPConnection
        connection = cls(self._origin.hostname, self._origin.port, timeout=self._timeout)
        try:
            body = {"nonce": nonce, "binding": asdict(binding)}
            if ticket is not None:
                body["ticket"] = ticket
            connection.request("POST", path,
                body=json.dumps(body),
                headers={"Authorization": "Bearer " + self._secret, "Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise ValueError()
            result = json.loads(raw)
            if path == PATH:
                token = result.get("ticket")
                if (not isinstance(token, str) or len(token) != 64
                        or result != {"fenced": True, "nonce": nonce, "ticket": token}):
                    raise ValueError()
                return token
            if result != {"enabled": True, "nonce": nonce}:
                raise ValueError()
        except Exception:
            raise BrowserUnavailable("viewer fencing was not acknowledged") from None
        finally:
            connection.close()
