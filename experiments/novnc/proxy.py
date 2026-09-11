"""Synthetic-only cookie admission and lifecycle wiring for websockify 0.10.

Never deploy this fixture session issuer. It deliberately grants a synthetic
owner to anyone reaching the loopback experiment, without SSO.
"""
import select
import socket
from http.cookies import SimpleCookie

from websockify.websocketproxy import LibProxyServer, ProxyRequestHandler

ORIGIN = "https://127.0.0.1:16080"
COOKIE = "__Host-CBViewer"
FIXTURE_HEADERS = {"Remote-Sub": "fixture-sub", "Remote-Groups": "PMOC_Users"}


class FixtureProxy(ProxyRequestHandler):
    def log_message(self, *args):
        pass  # Never log request cookies, URLs or protocol data.

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            return cookie[COOKIE].value
        except Exception:
            return ""

    def validate_connection(self):
        if self.path != "/websockify" or self.headers.get("Origin") != ORIGIN:
            raise self.CClose(1008, "Viewer unavailable")
        try:
            self.server.authority.authorize_stream(trusted_headers=FIXTURE_HEADERS, token=self.token())
        except PermissionError:
            raise self.CClose(1008, "Viewer unavailable") from None

    def do_GET(self):
        super().do_GET()

    def do_POST(self):
        if self.path != "/fixture-revoke" or self.headers.get("Origin") != ORIGIN:
            self.send_error(403)
            return
        self.server.store.revoke(self.token())
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_proxy(self, target):
        # Fixed private target, observation-only x11vnc, no dynamic target plugin.
        target.settimeout(1)
        pending = False
        outgoing = bytearray()

        def send(data):
            nonlocal pending
            pending = self.send_frames([data] if data else [])

        def close():
            self.send_parts.clear()  # Never flush stale queued display data.
            outgoing.clear()
            try:
                target.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        connection = self.server.authority.connect(
            trusted_headers=FIXTURE_HEADERS, token=self.token(),
            send_frame=send, close_transport=close,
        )
        try:
            while connection.poll():
                readable, writable, _ = select.select(
                    [self.request] + ([] if pending else [target]),
                    ([self.request] if pending else []) + ([target] if outgoing else []),
                    [], 0.1,
                )
                if not connection.poll():
                    break
                if self.request in writable and not connection.forward_frame(b""):
                    break
                if self.request in readable:
                    chunks, closed = self.recv_frames()
                    if closed:
                        break
                    for chunk in chunks:
                        if len(outgoing) + len(chunk) > 1024 * 1024:
                            raise ValueError("fixture input limit")
                        outgoing.extend(chunk)
                if target in writable and outgoing:
                    if not connection.poll():
                        break
                    count = target.send(outgoing)
                    del outgoing[:count]
                if target in readable:
                    data = target.recv(65536)
                    if not data or not connection.forward_frame(data):
                        break
        finally:
            connection.revoke()


def build_proxy(authority, store):
    server = LibProxyServer(
        RequestHandlerClass=FixtureProxy, listen_host="127.0.0.1", listen_port=6082,
        target_host="127.0.0.1", target_port=5900, web="/usr/share/novnc",
    )
    server.daemon_threads = True
    server.store = store
    server.authority = authority
    return server
