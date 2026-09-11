"""Loopback-published HTTPS gateway with a FIXED SYNTHETIC identity.

No authentication: everyone reaching this disposable gateway is fixture-owner.
Never deploy it. It exists to exercise Secure cookies and WSS locally.
"""
import http.client
import select
import socket
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIXTURE_HEADERS = {"Remote-Sub": "fixture-sub", "Remote-Groups": "PMOC_Users"}


def build_gateway(cert, key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/fixture-session":
                body = b'''<!doctype html><title>Synthetic viewer gateway</title>
                <p>Disposable synthetic identity. No SSO or credentials.</p>
                <button onclick="fetch('/ui/viewer/session',{method:'POST'}).then(r=>{
                if(r.status===204)location.href='/vnc.html?autoconnect=1&resize=scale';
                else document.querySelector('p').textContent='Viewer unavailable';})">Open read-only viewer</button>'''
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.headers.get("Upgrade", "").lower() == "websocket":
                self.tunnel()
            else:
                self.forward(6082)

        def do_POST(self):
            self.forward(6081 if self.path == "/ui/viewer/session" else 6082)

        def forwarded_headers(self):
            # Strip all caller identity attributes; replace with fixture identity.
            headers = {k: v for k, v in self.headers.items() if not k.lower().startswith("remote-")}
            headers.update(FIXTURE_HEADERS)
            return headers

        def forward(self, port):
            length = int(self.headers.get("Content-Length", "0"))
            if length != 0 or self.headers.get("Transfer-Encoding"):
                self.send_error(400)
                self.close_connection = True
                return
            client = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                client.request(self.command, self.path, headers=self.forwarded_headers())
                response = client.getresponse()
                data = response.read(4 * 1024 * 1024)
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in ("connection", "transfer-encoding", "content-length", "server", "date"):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                client.close()

        def tunnel(self):
            self.close_connection = True
            with socket.create_connection(("127.0.0.1", 6082), timeout=2) as target:
                headers = self.forwarded_headers()
                request = f"GET {self.path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
                target.sendall(request.encode("latin-1"))
                while True:
                    readable, _, _ = select.select([self.connection, target], [], [], 0.1)
                    if self.connection.pending() and self.connection not in readable:
                        readable.append(self.connection)
                    for source in readable:
                        data = source.recv(65536)
                        if not data:
                            return
                        (target if source is self.connection else self.connection).sendall(data)

    server = ThreadingHTTPServer(("0.0.0.0", 6080), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server
