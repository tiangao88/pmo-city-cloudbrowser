"""Disposable A/B/A display teardown proof; no production profiles or secrets.

Run as the sole entrypoint in the experimental container. Uses actual Chromium,
Xvfb, x11vnc and raw framebuffer pixels, not a browser mock. No public ports.
"""
import socket
import struct
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from cloudbrowser.browser_slots.browser_process import (
    BrowserProcess, BrowserProcessConfig, chrome_version_is_ready, request_chromium_shutdown,
)
from cloudbrowser.browser_slots.chrome_adapter import ChromeHttpClient, ChromeBrowserAdapter
from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer import AuthenticatedViewer, ViewerSessionStore
from cloudbrowser.viewer.slot_authority import SlotViewerAuthority
from cloudbrowser.viewer.fence_control import create_fence_server, ViewerFenceClient

COLOURS = {"alice": "e61919", "bob": "1919e6"}
SECRET = "synthetic-owner-switch-control-only"


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        owner = self.path.strip("/")
        if owner not in COLOURS:
            self.send_error(404)
            return
        body = (f"<!doctype html><title>{owner}-display-canary</title>"
                f"<style>html,body{{height:100%;margin:0;background:#{COLOURS[owner]}}}</style>"
                f"<h1>{owner} synthetic display</h1>").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


def exact(sock, length):
    data = bytearray()
    while len(data) < length:
        part = sock.recv(length - len(data))
        if not part:
            raise RuntimeError("framebuffer connection closed")
        data.extend(part)
    return bytes(data)


def framebuffer(sock):
    assert exact(sock, 12).startswith(b"RFB 003.")
    sock.sendall(b"RFB 003.008\n")
    count = exact(sock, 1)[0]
    assert 1 in exact(sock, count)
    sock.sendall(b"\x01")
    assert exact(sock, 4) == b"\x00" * 4
    sock.sendall(b"\x01")
    init = exact(sock, 24)
    width, height = struct.unpack("!HH", init[:4])
    assert 0 < width <= 1280 and 0 < height <= 800
    exact(sock, struct.unpack("!I", init[20:])[0])
    sock.sendall(struct.pack("!B3xBBBBHHHBBB3x", 0, 32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
    sock.sendall(struct.pack("!BBHi", 2, 0, 1, 0))  # Only raw encoding.
    sock.sendall(struct.pack("!BBHHHH", 3, 0, 0, 0, width, height))
    pixels = bytearray(width * height * 4)
    for _ in range(10):
        kind = exact(sock, 1)[0]
        if kind == 3:
            cut = exact(sock, 7)
            length = struct.unpack("!I", cut[3:])[0]
            assert length <= 65536
            exact(sock, length)
            continue
        if kind == 2:
            continue
        assert kind == 0
        rectangles = struct.unpack("!H", exact(sock, 3)[1:])[0]
        for _ in range(rectangles):
            x, y, w, h, encoding = struct.unpack("!HHHHi", exact(sock, 12))
            assert encoding == 0 and x + w <= width and y + h <= height
            data = exact(sock, w * h * 4)
            for row in range(h):
                offset = ((y + row) * width + x) * 4
                pixels[offset:offset + w * 4] = data[row * w * 4:(row + 1) * w * 4]
        return bytes(pixels)
    raise RuntimeError("no framebuffer update")


def main():
    fixture = ThreadingHTTPServer(("127.0.0.1", 8088), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    state = {"binding": None}
    def readiness():
        b = state["binding"]
        return BrowserReadiness(b.principal_id, b.generation, True) if b else BrowserReadiness("none", "none", False)
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=time.monotonic), token_secret=b"synthetic-owner-switch")
    authority = SlotViewerAuthority(viewer=viewer,
        identity_client=SimpleNamespace(resolve=lambda identity: identity.sub),
        readiness=readiness, stream_endpoint="/stream")
    control = create_fence_server(authority, shared_secret=SECRET, reset_display=lambda: None)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    client = ViewerFenceClient(base_url=f"http://127.0.0.1:{control.server_port}", shared_secret=SECRET)
    browser = display = vnc = old_socket = old_live = None
    old_session = old_binding = None
    display_pids = []
    try:
        with tempfile.TemporaryDirectory(prefix="owner-switch-") as temporary:
            for index, owner in enumerate(("alice", "bob", "alice"), 1):
                binding = BrowserBinding(f"profile-{owner}", owner, "fixture-browser", f"g{index}")
                client(old_binding or binding)  # Must acknowledge before any teardown.
                if old_socket is not None:
                    assert old_socket.fileno() == -1 and old_live.closed
                    assert not old_live.forward_frame(b"stale")
                state["binding"] = None
                if browser is not None:
                    browser.stop()
                stop_process(vnc)
                stop_process(display)
                assert display is None or display.poll() is not None
                display = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                display_pids.append(display.pid)
                for _ in range(50):
                    if subprocess.run(["xdpyinfo"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("new display not ready")
                chrome = ChromeHttpClient("http://127.0.0.1:9222")
                root = Path(temporary) / f"round-{index}"
                browser = BrowserProcess(BrowserProcessConfig(executable="/usr/bin/chromium",
                    profile_dir=root, profile_root=root, http_port=9222, owner=owner,
                    profile_id=binding.profile_id, browser_id=binding.browser_id, generation=binding.generation,
                    extra_args=("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1280,800")),
                    probe=lambda: chrome_version_is_ready(chrome.json_request("/json/version")),
                    graceful_shutdown=lambda: request_chromium_shutdown(chrome))
                browser.start()
                adapter = ChromeBrowserAdapter(chrome, owner=owner, generation=binding.generation)
                adapter.open_page(f"http://127.0.0.1:8088/{owner}")
                for _ in range(50):
                    pages = chrome.json_request("/json/list")
                    if any(p.get("title") == f"{owner}-display-canary" for p in pages):
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("canary page not ready")
                time.sleep(0.5)  # Let the synthetic canary paint before VNC capture.
                vnc = subprocess.Popen(["x11vnc", "-display", ":99", "-localhost", "-rfbport", "5900",
                    "-forever", "-shared", "-nopw", "-viewonly", "-nosel", "-noremote", "-noxdamage"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(50):
                    try:
                        stream = socket.create_connection(("127.0.0.1", 5900), timeout=2)
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("VNC not ready")
                state["binding"] = binding
                client.enable(binding)
                headers = {"Remote-Sub": owner, "Remote-Groups": "PMOC_Users"}
                if old_session:
                    try:
                        authority.authorize_stream(trusted_headers=headers, token=old_session.token)
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError("previous cookie accepted")
                session = authority.issue_leased(trusted_headers=headers)
                delivered = []
                live = authority.connect(trusted_headers=headers, token=session.token,
                    send_frame=delivered.append, close_transport=stream.close)
                pixels = framebuffer(stream)
                assert live.forward_frame(pixels)
                colour = bytes.fromhex(COLOURS[owner])[::-1]
                other = bytes.fromhex(COLOURS["bob" if owner == "alice" else "alice"])[::-1]
                matching = sum(pixels[i:i + 3] == colour for i in range(0, len(pixels), 4))
                previous = sum(pixels[i:i + 3] == other for i in range(0, len(pixels), 4))
                assert matching > 100000 and previous == 0, (owner, matching, previous)
                print(f"PASS round {index}: {owner}; fresh X display; {matching} owner-colour pixels; no other-owner colour", flush=True)
                old_binding, old_session, old_socket, old_live = binding, session, stream, live
            assert len(set(display_pids)) == 3
            client(old_binding)
            print("PASS A/B/A: old streams closed before teardown and old cookies rejected", flush=True)
            browser.stop()
            browser = None
    finally:
        if old_socket is not None:
            old_socket.close()
        if browser is not None:
            browser.stop()
        stop_process(vnc)
        stop_process(display)
        for server in (control, fixture):
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
