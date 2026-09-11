"""Private, opt-in viewer fencing RPC. Not exposed by the deployed runtime.

Only closes authority; never opens a viewer or enables human input. Deploying
this requires a private authenticated service network, not a public UI route.
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

PATH = "/internal/viewer/fence"


def create_fence_server(authority, *, shared_secret, address=("127.0.0.1", 0)):
    if not isinstance(shared_secret, str) or len(shared_secret) < 32:
        raise ValueError("fence secret must contain at least 32 characters")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != PATH or not hmac.compare_digest(
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
                authority.fence(BrowserBinding(**raw))
            except Exception:
                self.send_error(409, "Viewer fence unavailable")
                return
            payload = json.dumps({"fenced": True, "nonce": nonce}).encode()
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

    def __call__(self, binding):
        nonce = secrets.token_hex(16)
        cls = http.client.HTTPSConnection if self._origin.scheme == "https" else http.client.HTTPConnection
        connection = cls(self._origin.hostname, self._origin.port, timeout=self._timeout)
        try:
            connection.request("POST", PATH,
                body=json.dumps({"nonce": nonce, "binding": asdict(binding)}),
                headers={"Authorization": "Bearer " + self._secret, "Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                raise ValueError()
            if json.loads(raw) != {"fenced": True, "nonce": nonce}:
                raise ValueError()
        except Exception:
            raise BrowserUnavailable("viewer fencing was not acknowledged") from None
        finally:
            connection.close()
