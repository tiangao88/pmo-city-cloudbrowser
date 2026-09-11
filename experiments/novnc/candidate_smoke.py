"""Synthetic candidate runtime HTTPS/WSS smoke. No network or real accounts.

Run as a disposable container entrypoint with this directory mounted read-only.
The mock identity service is a fixture, not authentication qualification.
"""
import http.client
import json
import os
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cloudbrowser.browser_slots.lifecycle import BrowserBinding, OwnerBoundLifecycle
from cloudbrowser.browser_slots.supervisor import SlotSupervisor
from cloudbrowser.browser_slots.http_client import HttpJsonClient
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.viewer.fence_control import ViewerFenceClient
from gateway import build_gateway
from test_proxy import connect
from held_input import held_input
from owner_switch import framebuffer, COLOURS
from wss_rfb import RfbWebSocket

ORIGIN = "https://127.0.0.1:16080"
SECRET = "synthetic-candidate-control-only-32"


class Identity(BaseHTTPRequestHandler):
    state = None

    def do_GET(self):
        data = (b'<!doctype html><title>Synthetic desktop input</title><h1>Synthetic desktop input</h1>'
                b'<p>No credentials or external sites.</p><input autofocus style="font:24px sans-serif">'
                if self.path == "/task" else b'{"status":"ok"}')
        if self.path == "/task":
            data += ('<style>html,body{background:#' + COLOURS[self.state["owner"]] + ';height:100%;margin:0}</style>').encode()
            data += ("<script>requestAnimationFrame(()=>requestAnimationFrame(()=>fetch('/painted/"
                     + self.state["owner"] + "')))</script>").encode()
        if self.path == "/painted/" + self.state["owner"]:
            self.state["painted"] = True
        self.send_response(200)
        if self.path == "/task":
            self.state["seen"].append(self.headers.get("Cookie", ""))
            self.send_header("Set-Cookie", "cb_synthetic_owner=" + self.state["owner"] + "; Max-Age=3600; Path=/")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        data = json.dumps({"principal_id": body["external_id"]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def request(port, path, *, data=None, headers=None, tls=False):
    connection = (http.client.HTTPSConnection("127.0.0.1", port, timeout=15,
        context=ssl._create_unverified_context()) if tls else
        http.client.HTTPConnection("127.0.0.1", port, timeout=15))
    try:
        connection.request("POST" if data is not None else "GET", path, body=data, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def main():
    state = {"owner": "alice", "seen": []}
    Identity.state = state
    servers = []
    child = None
    streams = []
    with tempfile.TemporaryDirectory(prefix="candidate-smoke-") as temporary:
        from cloudbrowser.broker_jobs import BrokerJobs
        jobs_directory = Path(temporary) / "jobs"
        jobs_directory.mkdir(mode=0o700)
        broker_jobs = BrokerJobs(jobs_directory)
        try:
            identity = ThreadingHTTPServer(("127.0.0.1", 8091), Identity)
            servers.append(identity)
            cert, key = Path(temporary) / "cert.pem", Path(temporary) / "key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=127.0.0.1"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            servers.append(build_gateway(cert, key, backend_port=8082,
                fixture_headers=lambda: {"Remote-Sub": state["owner"], "Remote-Groups": "PMOC_Users"}))
            for server in servers:
                threading.Thread(target=server.serve_forever, daemon=True).start()
            env = {**os.environ, "CB_EXPERIMENTAL_DESKTOP": "1", "CB_EDGE_AUTH": "traefik-forwardauth",
                "CB_EXPERIMENTAL_BROKER_JOBS_DIR": str(jobs_directory),
                "CB_VIEWER_PUBLIC_ORIGIN": ORIGIN, "CB_VIEWER_CONTROL_SECRET": SECRET,
                "CB_VIEWER_TOKEN_SECRET": "synthetic-viewer-token-secret-only-32",
                "CB_ROUTER_BASE_URL": "http://127.0.0.1:8080", "CB_ROUTER_SHARED_SECRET": SECRET,
                "CB_IDENTITY_LINK_BASE_URL": "http://127.0.0.1:8091", "CB_IDENTITY_LINK_SHARED_SECRET": SECRET,
                "CB_OIDC_ISSUER": "https://identity.example.test", "CB_TINYAUTH_REALM": "fixture",
                "CB_INSTANCE_ID": "candidate-smoke", "CB_RELEASE_VERSION": "unqualified",
                "CB_PROFILE_DIR": str(Path(temporary) / "profiles")}
            child = subprocess.Popen([sys.executable, "-m", "cloudbrowser.viewer.desktop_runtime"], env=env)
            for _ in range(100):
                assert child.poll() is None, "candidate exited"
                try:
                    if request(9230, "/browser/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError("candidate unavailable")
            client = ViewerFenceClient(base_url="http://127.0.0.1:6083", shared_secret=SECRET)
            previous = BrowserBinding("profile-unassigned", "principal-unassigned", "browser-unassigned", "generation-0")
            os.environ["CB_ROUTER_SHARED_SECRET"] = SECRET
            supervisor = SlotSupervisor(OwnerBoundLifecycle(previous, Path(temporary) / "tabs.json"),
                HttpBrowserTransport(HttpJsonClient("http://127.0.0.1:9230", timeout_s=15),
                    expected_owner=previous.principal_id, expected_generation=previous.generation),
                native_tab_restore=True, viewer_fence=client, viewer_enable=client.enable, viewer_renew=client.renew)
            old_cookie = None
            old_stream = None
            for index, owner in enumerate(("alice", "bob", "alice", "alice")):
                if index == 3:
                    child.terminate()
                    child.wait(timeout=15)
                    child = subprocess.Popen([sys.executable, "-m", "cloudbrowser.viewer.desktop_runtime"], env=env)
                    for _ in range(100):
                        assert child.poll() is None
                        try:
                            if request(9230, "/browser/health")[0] == 200:
                                break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise AssertionError("candidate restart unavailable")
                    # A new process must not accept the previous controller ticket.
                    try:
                        client.renew(previous)
                    except Exception:
                        pass
                    else:
                        raise AssertionError("old controller survived restart")
                binding = previous if index == 3 else BrowserBinding("profile-" + owner, owner, "browser-unassigned", "g" + str(index))
                state.update(owner=owner, seen=[], painted=False)
                if index != 3:
                    supervisor.adopt_binding(binding)
                if old_stream is not None:
                    drained = 0
                    while chunk := old_stream.recv(65536):
                        drained += len(chunk)
                        assert drained < 8 * 1024 * 1024
                    old_stream.close()
                    print("PASS old live WSS transport closed before next wake", flush=True)
                assert supervisor.wake(binding).status == "ready"
                assert request(9230, "/browser/pages/open", data=b"http://127.0.0.1:8091/task")[0] == 200
                for _ in range(50):
                    if state["seen"]:
                        break
                    time.sleep(.1)
                assert state["seen"], "fixture page did not load"
                for _ in range(50):
                    if state["painted"]:
                        break
                    time.sleep(.1)
                assert state["painted"], "fixture did not reach two animation frames"
                assert state["seen"][0] == ("" if index < 2 else "cb_synthetic_owner=alice"), "profile cookie continuity failed"
                state["owner"] = owner
                if old_cookie:
                    assert request(6080, "/desktop.html", headers={"Cookie": old_cookie}, tls=True)[0] == 403
                status, headers, _ = request(6080, "/ui/viewer/session", data=b"", headers={"Origin": ORIGIN}, tls=True)
                assert status == 204, status
                value = headers["Set-Cookie"].split(";", 1)[0]
                h = {"Origin": ORIGIN, "Cookie": value}
                assert request(6080, "/desktop.html", headers=h, tls=True)[0] == 200
                pixels_stream = RfbWebSocket(value)
                streams.append(pixels_stream)
                pixels = framebuffer(pixels_stream)
                own = bytes.fromhex(COLOURS[owner])[::-1]
                other = bytes.fromhex(COLOURS["bob" if owner == "alice" else "alice"])[::-1]
                own_count = sum(pixels[i:i + 3] == own for i in range(0, len(pixels), 4))
                other_count = sum(pixels[i:i + 3] == other for i in range(0, len(pixels), 4))
                assert own_count > 100000 and other_count == 0, (
                    f"first framebuffer owner canary mismatch: owner={own_count}, other={other_count}")
                pixels_stream.close()
                print(f"PASS first WSS framebuffer {owner}: {own_count} owner pixels, zero other-owner pixels", flush=True)
                with broker_jobs.job(broker_jobs.snapshot()):
                    assert request(6080, "/ui/viewer/takeover", data=b"", headers=h, tls=True)[0] == 403
                    assert request(9230, "/agent/pages")[0] == 503
                    assert request(6080, "/ui/viewer/resume", data=b"", headers=h, tls=True)[0] == 403
                print("PASS separate-process synthetic job blocks takeover/resume until exit", flush=True)
                assert request(6080, "/ui/viewer/takeover", data=b"", headers=h, tls=True)[0] == 200
                assert request(9230, "/agent/pages")[0] == 503
                assert request(9230, "/broker/basic/probe", data=b"{}")[0] == 503
                stream = connect(value)
                streams.append(stream)
                received = b""
                while b"RFB 003" not in received:
                    chunk = stream.recv(4096)
                    assert chunk, "stream closed before RFB"
                    received += chunk
                    assert len(received) < 65536
                assert held_input(press=True) == (True, True)
                stream.close()
                for _ in range(50):
                    status, _, body = request(6080, "/ui/viewer/status", data=b"", headers=h, tls=True)
                    if status == 200 and json.loads(body)["mode"] == "paused":
                        break
                    time.sleep(.1)
                else:
                    raise AssertionError("disconnect did not pause")
                assert held_input() == (False, False), "disconnect retained held input"
                assert request(6080, "/ui/viewer/resume", data=b"", headers=h, tls=True)[0] == 200
                assert request(9230, "/browser/pages")[0] == 200
                print(f"PASS {owner} round {index}: HTTPS cookie, WSS RFB, takeover exclusion, disconnect pause, resume", flush=True)
                previous, old_cookie = binding, value
                if index == 0:
                    assert supervisor.suspend(binding).status == "suspended"
                    assert supervisor.wake(binding).status == "ready"
                    print("PASS supervisor suspend snapshot after fence and resume", flush=True)
                _, headers, _ = request(6080, "/ui/viewer/session", data=b"", headers={"Origin": ORIGIN}, tls=True)
                old_cookie = headers["Set-Cookie"].split(";", 1)[0]
                old_stream = RfbWebSocket(old_cookie)
                streams.append(old_stream)
                framebuffer(old_stream)
            if os.environ.get("CB_SMOKE_SERVE") != "1":
                for executable in ("Xvfb", "chromium", "x11vnc"):
                    _, headers, _ = request(6080, "/ui/viewer/session", data=b"", headers={"Origin": ORIGIN}, tls=True)
                    value = headers["Set-Cookie"].split(";", 1)[0]
                    stream = RfbWebSocket(value)
                    streams.append(stream)
                    framebuffer(stream)
                    victims = []
                    for process_dir in Path("/proc").iterdir():
                        if not process_dir.name.isdigit():
                            continue
                        try:
                            status = (process_dir / "status").read_text()
                            args = (process_dir / "cmdline").read_bytes().split(b"\0")
                        except OSError:
                            continue
                        parent = next((line.split()[1] for line in status.splitlines() if line.startswith("PPid:")), "")
                        if parent == str(child.pid) and Path(os.fsdecode(args[0])).name == executable:
                            victims.append(int(process_dir.name))
                    assert len(victims) == 1, "expected one owned runtime child"
                    os.kill(victims[0], signal.SIGKILL)
                    for _ in range(100):
                        code, _, body = request(9230, "/browser/health")
                        if code == 200 and json.loads(body)["browser_state"] == "stopped":
                            break
                        time.sleep(.1)
                    else:
                        raise AssertionError("crash did not stop the complete desktop")
                    assert request(6080, "/desktop.html", headers={"Cookie": value}, tls=True)[0] == 403
                    drained = 0
                    while chunk := stream.recv(65536):
                        drained += len(chunk)
                        assert drained < 8 * 1024 * 1024
                    stream.close()
                    assert supervisor.wake(previous).status == "ready"
                    assert request(6080, "/desktop.html", headers={"Cookie": value}, tls=True)[0] == 403
                    _, headers, _ = request(6080, "/ui/viewer/session", data=b"", headers={"Origin": ORIGIN}, tls=True)
                    fresh = RfbWebSocket(headers["Set-Cookie"].split(";", 1)[0])
                    streams.append(fresh)
                    pixels = framebuffer(fresh)
                    assert sum(pixels[i:i + 3] == bytes.fromhex(COLOURS["bob"])[::-1] for i in range(0, len(pixels), 4)) == 0
                    fresh.close()
                    print(f"PASS {executable} crash: stream closed, old cookie rejected, supervisor recovery and clean first frame", flush=True)
            if os.environ.get("CB_SMOKE_SERVE") == "1":
                print("Synthetic localhost viewer ready for visual QA", flush=True)
                while child.poll() is None:
                    client.renew(previous)
                    time.sleep(3)
            else:
                time.sleep(16)  # The private authority lease is bounded to 15s.
                assert request(9230, "/agent/pages")[0] == 503
                assert request(6080, "/ui/viewer/session", data=b"", headers={"Origin": ORIGIN}, tls=True)[0] == 403
                try:
                    client.renew(previous)
                except Exception:
                    pass
                else:
                    raise AssertionError("renewal revived expired authority")
                print("PASS expired lease pauses agent and rejects issuance/renewal", flush=True)
                assert supervisor.wake(previous).status == "ready"
                assert request(6080, "/ui/viewer/session", data=b"", headers={"Origin": ORIGIN}, tls=True)[0] == 204
                print("PASS explicit already-ready wake repairs expired viewer authority", flush=True)
            client(previous)
            print("PASS profile-cookie A/B/A, first WSS framebuffer and runtime restart; synthetic qualification only", flush=True)
        finally:
            for stream in streams:
                stream.close()
            if child:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            for server in reversed(servers):
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
