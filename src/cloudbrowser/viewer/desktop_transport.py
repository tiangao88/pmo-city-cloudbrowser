"""noVNC transport for the separate desktop candidate image (websockify 0.10).

Public port must be behind a sanitizing authenticated edge. Raw VNC is loopback.
"""
import http.client
import errno
import select
import socket
from http.cookies import SimpleCookie

from websockify.websocketproxy import LibProxyServer, ProxyRequestHandler

DESKTOP = b'''<!doctype html><meta charset="utf-8"><title>CloudBrowser desktop</title>
<style>html,body,#screen{margin:0;width:100%;height:100%;overflow:hidden;background:#222}</style>
<div id="screen"></div><script type="module">
import RFB from './core/rfb.js';
const rfb = new RFB(document.getElementById('screen'), `wss://${location.host}/websockify`);
rfb.scaleViewport=true;
rfb.addEventListener('disconnect',()=>parent.postMessage({type:'viewer-disconnected'},location.origin));
</script>'''

CONTROLS = '''<section><h2>Live browser</h2>
<p id="desktop-status">Read-only until you take control. Disconnect leaves the agent paused.</p>
<button onclick="desktopOpen()">Open desktop</button>
<button onclick="desktopControl('takeover')">Take control</button>
<button onclick="desktopControl('resume')">Resume agent</button>
<iframe id="desktop" title="CloudBrowser desktop" style="width:100%;height:70vh;border:1px solid #ccc"></iframe>
<script>
async function desktopOpen(){const r=await fetch('/ui/viewer/session',{method:'POST'});
if(r.status===204)document.getElementById('desktop').src='/desktop.html';
else document.getElementById('desktop-status').textContent='Viewer unavailable: activate your session first.';}
async function desktopControl(action){const r=await fetch('/ui/viewer/'+action,{method:'POST'});
if(!r.ok){document.getElementById('desktop-status').textContent='Control unavailable';return;}
const state=await r.json();document.getElementById('desktop-status').textContent='Control: '+state.mode;
document.getElementById('desktop').src='/desktop.html?epoch='+Date.now();}
addEventListener('message',e=>{if(e.origin===location.origin&&e.source===document.getElementById('desktop').contentWindow&&e.data?.type==='viewer-disconnected')
document.getElementById('desktop-status').textContent='Disconnected. Agent does not resume automatically.';});
</script></section>'''


def create_desktop_transport(authority, *, public_origin, ui_port=6081, port=8082):
    class Handler(ProxyRequestHandler):
        def log_message(self, *args):
            pass

        def new_websocket_client(self):
            try:
                super().new_websocket_client()
            except OSError as exc:
                # Our synchronous fence has already shut down the VNC socket;
                # websockify 0.10 attempts a second shutdown in its finally.
                if exc.errno != errno.ENOTCONN:
                    raise

        def token(self):
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            return cookie["__Host-CBViewer"].value

        def trusted_headers(self):
            names = [name.lower() for name in self.headers.keys()]
            if len(names) != len(set(names)):
                raise PermissionError("duplicate headers")
            return dict(self.headers.items())

        def validate_connection(self):
            try:
                if self.path != "/websockify" or self.headers.get("Origin") != public_origin:
                    raise PermissionError()
                authority.authorize_stream(trusted_headers=self.trusted_headers(), token=self.token())
            except Exception:
                raise self.CClose(1008, "Viewer unavailable") from None

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/desktop.html":
                try:
                    authority.authorize_stream(trusted_headers=self.trusted_headers(), token=self.token())
                except Exception:
                    self.send_error(403)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(DESKTOP)))
                self.end_headers()
                self.wfile.write(DESKTOP)
            elif self.path in ("/", "/viewer", "/health") or self.path.startswith("/ui/"):
                self.forward_ui()
            else:
                super().do_GET()

        def do_POST(self):
            if not self.path.startswith("/ui/"):
                self.send_error(404)
                return
            self.forward_ui()

        def forward_ui(self):
            try:
                headers = self.trusted_headers()
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 8192 or self.headers.get("Transfer-Encoding"):
                    raise ValueError()
            except Exception:
                self.send_error(400)
                self.close_connection = True
                return
            self.connection.settimeout(5)
            body = self.rfile.read(length) if length else None
            client = http.client.HTTPConnection("127.0.0.1", ui_port, timeout=10)
            try:
                client.request(self.command, self.path, body=body, headers=headers)
                response = client.getresponse()
                data = response.read(128 * 1024)
                if response.status == 200 and self.path in ("/", "/viewer"):
                    data = data.replace(b"</main>", CONTROLS.encode() + b"</main>")
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in ("connection", "transfer-encoding", "content-length", "server", "date"):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            finally:
                client.close()

        def do_proxy(self, target):
            target.settimeout(1)
            pending = False
            outgoing = bytearray()
            def send(data):
                nonlocal pending
                pending = self.send_frames([data] if data else [])
            def close():
                self.send_parts.clear()
                outgoing.clear()
                try:
                    target.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection = authority.connect(trusted_headers=self.trusted_headers(), token=self.token(),
                send_frame=send, close_transport=close)
            try:
                while connection.poll():
                    readable, writable, _ = select.select([self.request] + ([] if pending else [target]),
                        ([self.request] if pending else []) + ([target] if outgoing else []), [], 0.1)
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
                                raise ValueError("viewer input limit")
                            outgoing.extend(chunk)
                    if target in writable and outgoing:
                        # Serialize input writes with takeover/lease/owner changes.
                        with authority._lock:
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

    server = LibProxyServer(RequestHandlerClass=Handler, listen_host="0.0.0.0", listen_port=port,
        target_host="127.0.0.1", target_port=5900, web="/usr/share/novnc")
    server.daemon_threads = True
    return server
