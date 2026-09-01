#!/usr/bin/env python3
"""W1+W2 window-manager: keep every Chrome window pinned to the full virtual
screen (neko Xvfb, no WM — so explicit bounds, not 'maximized' state).

Pure stdlib (no websockets dependency — apt installs do not survive
container recreates). Polls every 4s via CDP browser ws:
  for each page target with a real window -> getWindowBounds ->
  if not at {0,0,WM_SCREEN} -> setWindowBounds {0,0,WM_SCREEN}.

W2 (2026-08-17) additions:
  - kiosk-safe: windows whose state is "fullscreen" (Chrome --kiosk) are
    never re-pinned (pinning with windowState=normal would fight kiosk).
  - extension popups (chrome-extension:// page targets, window width <
    POPUP_MAX_W) are NOT pinned fullscreen and are CLOSED after
    POPUP_GRACE_SECS — kills stale parked popups (19-viewer-test-findings
    F-6: two Bitwarden popup windows sat at 0,0 480x630 forever). 60 s
    grace covers normal unlock/autofill usage.

WM_SCREEN env overrides the default 1920x1080 (must match NEKO_SCREEN).
"""
import base64
import hashlib
import json
import os
import select
import socket
import struct
import time
import urllib.request

WM_SCREEN = os.environ.get("WM_SCREEN", "1920x1080")
W, H = (int(v.split("@")[0]) for v in WM_SCREEN.split("x"))
POLL_SECS = 4
CDP_HTTP = "http://127.0.0.1:9222"
SET_COOLDOWN = 30  # don't re-issue setWindowBounds more than once per 30s/window
POPUP_MAX_W = 700   # extension popup windows are smaller than this
POPUP_GRACE_SECS = 300  # close parked popups after 5 min (60s killed
                        # mid-unlock Bitwarden popups — F-6 roll-up)


def http_json(path: str):
    with urllib.request.urlopen(CDP_HTTP + path, timeout=5) as r:
        return json.load(r)


class CDPWs:
    """Minimal websocket client for the CDP browser endpoint."""

    def __init__(self, url: str):
        host, _, port_path = url[len("ws://"):].partition(":")
        port, _, path = port_path.partition("/")
        self.sock = socket.create_connection((host, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        self._buf = b""
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake: connection closed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"handshake failed: {head[:80]!r}")
        self._buf = head.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("ws closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send_json(self, obj) -> None:
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            hdr = bytes([0x81, 0x80 | n])
        elif n < 65536:
            hdr = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(hdr + mask + payload)

    def recv_json(self, timeout: float):
        while True:
            ready, _, _ = select.select([self.sock], [], [], timeout)
            if not ready:
                raise TimeoutError("recv timeout")
            b0, b1 = self._read(2)
            opcode = b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            if b1 & 0x80:  # masked (server->client should not be)
                mask = self._read(4)
                payload = bytes(b ^ mask[i % 4]
                                for i, b in enumerate(self._read(n)))
            else:
                payload = self._read(n)
            if opcode == 0x9:  # ping -> pong
                self.sock.sendall(bytes([0x8A]) + struct.pack(">B", 0) + payload)
                continue
            if opcode == 0x1:  # text
                return json.loads(payload)
            if opcode == 0x8:  # close
                raise ConnectionError("ws closed by peer")


def main() -> None:
    print(f"window-manager: pinning windows to {W}x{H} every {POLL_SECS}s "
          f"(kiosk-safe, popup janitor {POPUP_GRACE_SECS}s)",
          flush=True)
    ws = None
    last_set = {}
    popup_seen = {}  # targetId -> first-seen monotonic ts
    while True:
        try:
            if ws is None:
                ver = http_json("/json/version")
                ws = CDPWs(ver["webSocketDebuggerUrl"])
            _id = 0

            def cmd(method: str, params: dict = None):
                nonlocal _id
                _id += 1
                ws.send_json({"id": _id, "method": method, "params": params or {}})
                while True:
                    m = ws.recv_json(15)
                    if m.get("id") == _id:
                        if "error" in m:
                            raise RuntimeError(
                                f"{method}: {m['error'].get('message', m['error'])}")
                        return m.get("result", {})

            targets = http_json("/json")
            for t in targets:
                if t.get("type") != "page":
                    continue
                is_ext_popup = t.get("url", "").startswith("chrome-extension://")
                try:
                    w = cmd("Browser.getWindowForTarget", {"targetId": t["id"]})
                    wid = w.get("windowId")
                    if wid is None:
                        continue  # orphan/windowless target
                    b = cmd("Browser.getWindowBounds", {"windowId": wid})["bounds"]
                    now = time.monotonic()
                    if is_ext_popup and b.get("width", 0) < POPUP_MAX_W:
                        # extension popup window: janitor duty, never pinned
                        first = popup_seen.setdefault(t["id"], now)
                        if now - first > POPUP_GRACE_SECS:
                            cmd("Target.closeTarget", {"targetId": t["id"]})
                            print(f"closed parked extension popup "
                                  f"{t['id'][:8]} ({t['url'][:50]})",
                                  flush=True)
                            popup_seen.pop(t["id"], None)
                        continue
                    popup_seen.pop(t["id"], None)
                    if b.get("windowState") == "fullscreen":
                        continue  # kiosk window — never re-pin (D7)
                    if (b.get("left"), b.get("top"),
                            b.get("width"), b.get("height")) != (0, 0, W, H) \
                            and now - last_set.get(wid, 0) > SET_COOLDOWN:
                        cmd("Browser.setWindowBounds", {
                            "windowId": wid,
                            "bounds": {"left": 0, "top": 0,
                                       "width": W, "height": H,
                                       "windowState": "normal"},
                        })
                        last_set[wid] = now
                        print(f"resized window {wid} to {W}x{H} "
                              f"({t['url'][:40]})", flush=True)
                except Exception as e:
                    print(f"window {t['id'][:8]}: {e}", flush=True)
        except Exception as e:
            print(f"poll error: {e} — reconnecting", flush=True)
            ws = None
            time.sleep(2)
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
