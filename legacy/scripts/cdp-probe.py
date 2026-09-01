#!/usr/bin/env python3
"""CDP probe for slot Chrome — replicates W1 failure tests on stock Chrome 133.
Pure stdlib (http.client + raw socket WS). Tests:
  1. /json/version + /json/list reachable (browser-level HTTP)
  2. Page-level WS: Runtime.evaluate  (W1: HANGS on 133+)
  3. Browser-level WS: Target.attachToTarget flatten:true (W1: -32001)
  4. If attach succeeds: session-scoped Runtime.evaluate (true CDP driving)
Prints VERDICT lines; exit 0 = CDP usable, 1 = broken like W1.
"""
import http.client, socket, base64, os, json, time, sys

HOST, PORT = sys.argv[1].split(":") if len(sys.argv) > 1 else ("127.0.0.1", 9222)
PORT = int(PORT)
WS_TIMEOUT = 8.0

def http_get(path, timeout=5):
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, data

def ws_connect(path, timeout=WS_TIMEOUT):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\n"
           f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    s.sendall(req.encode())
    s.settimeout(timeout)
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(4096)
        if not chunk:
            break
        resp += chunk
    if b"101" not in resp.split(b"\r\n", 1)[0]:
        return s, resp
    return s, None

def ws_send(s, obj):
    payload = json.dumps(obj).encode()
    n = len(payload)
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if n < 126:
        header = bytes([0x81, 0x80 | n])
    elif n < 65536:
        header = bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big")
    else:
        header = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big")
    s.sendall(header + mask + masked)

def ws_recv_json(s, want_id=None, timeout=WS_TIMEOUT):
    """Read WS frames until a JSON message with matching id (or any if want_id None)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s.settimeout(max(0.1, deadline - time.time()))
        try:
            hdr = s.recv(2)
            if len(hdr) < 2:
                return None, "closed"
            b1, b2 = hdr
            n = b2 & 0x7F
            if n == 126:
                n = int.from_bytes(s.recv(2), "big")
            elif n == 127:
                n = int.from_bytes(s.recv(8), "big")
            payload = b""
            while len(payload) < n:
                chunk = s.recv(n - len(payload))
                if not chunk:
                    break
                payload += chunk
            if not payload:
                continue
            try:
                msg = json.loads(payload)
            except Exception:
                continue
            if want_id is None or msg.get("id") == want_id:
                return msg, "ok"
        except socket.timeout:
            return None, "TIMEOUT"
        except Exception as e:
            return None, f"ERR {e}"
    return None, "TIMEOUT"

results = []
def report(name, ok, detail):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")

# 1. HTTP endpoints
try:
    st, body = http_get("/json/version")
    ver = json.loads(body)
    browser_ws = ver.get("webSocketDebuggerUrl")
    report("json/version", st == 200 and browser_ws, f"HTTP {st}, browser WS {browser_ws}")
except Exception as e:
    report("json/version", False, f"EXC {e}")
    browser_ws = None

try:
    st, body = http_get("/json/list")
    targets = json.loads(body)
    pages = [t for t in targets if t.get("type") == "page"]
    report("json/list", st == 200 and pages, f"HTTP {st}, {len(pages)} page targets")
    page_ws = pages[0]["webSocketDebuggerUrl"] if pages else None
except Exception as e:
    report("json/list", False, f"EXC {e}")
    page_ws = None

# 2. Page-level WS + Runtime.evaluate (W1: hang)
if page_ws:
    path = page_ws.split(f":{PORT}", 1)[1]
    try:
        s, hs_err = ws_connect(path)
        if hs_err is not None:
            report("page-WS handshake", False, hs_err[:120])
        else:
            ws_send(s, {"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": "1+1", "returnByValue": True}})
            t0 = time.time()
            msg, st = ws_recv_json(s, want_id=1)
            dt = time.time() - t0
            if st == "ok" and msg:
                val = msg.get("result", {}).get("result", {}).get("value")
                report("page-WS evaluate", "value" in str(msg.get("result", {})), f"reply in {dt:.1f}s, value={val} err={msg.get('error')}")
            else:
                report("page-WS evaluate", False, f"{st} after {dt:.1f}s (W1 hang signature)")
            s.close()
    except Exception as e:
        report("page-WS evaluate", False, f"EXC {e}")
else:
    report("page-WS evaluate", False, "no page target")

# 3+4. Browser-level WS: attachToTarget + session evaluate
if browser_ws:
    path = browser_ws.split(f":{PORT}", 1)[1]
    try:
        s, hs_err = ws_connect(path)
        if hs_err is not None:
            report("browser-WS handshake", False, hs_err[:120])
        else:
            tid = pages[0]["id"] if pages else None
            if tid:
                ws_send(s, {"id": 2, "method": "Target.attachToTarget",
                            "params": {"targetId": tid, "flatten": True}})
                msg, st = ws_recv_json(s, want_id=2)
                if st != "ok" or not msg:
                    report("attachToTarget", False, f"{st} (W1 -32001 signature)")
                    s.close()
                else:
                    err = msg.get("error")
                    if err:
                        report("attachToTarget", False, f"error {err['code']} {err['message']} (W1 signature)")
                        s.close()
                    else:
                        sid = msg["result"]["sessionId"]
                        report("attachToTarget", True, f"sessionId={sid[:16]}…")
                        ws_send(s, {"id": 3, "method": "Runtime.evaluate",
                                    "params": {"expression": "document.title", "returnByValue": True},
                                    "sessionId": sid})
                        msg, st = ws_recv_json(s, want_id=3)
                        if st == "ok" and msg:
                            val = msg.get("result", {}).get("result", {}).get("value")
                            report("session evaluate", val is not None, f"title={val!r} err={msg.get('error')}")
                        else:
                            report("session evaluate", False, f"{st} after attach")
                        s.close()
            else:
                report("attachToTarget", False, "no target id")
    except Exception as e:
        report("attachToTarget", False, f"EXC {e}")
else:
    report("attachToTarget", False, "no browser WS")

ok = all(results)
print(f"\nVERDICT: {'CDP-USABLE' if ok else 'CDP-BROKEN-LIKE-W1'}")
sys.exit(0 if ok else 1)
