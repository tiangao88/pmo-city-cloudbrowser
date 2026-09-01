#!/usr/bin/env python3
"""CDP relay v3 (instrumented): expose loopback-bound CDP 9222 on 0.0.0.0:9223.
Logs each connection + any exception to /tmp/cdp-relay.log (stderr also).

Spec 29 (2026-08-21): agent-activity signal. Every client->browser data
chunk (throttled to 1 write / 2 s) touches /tmp/cdp-activity with the
current epoch — restart-api's idle reaper reads its mtime as the agent
activity source (CDP commands bypass X11 and the router, so this is the
ONLY honest agent signal). Only CDP clients (agents) use :9223 — the neko
human path never touches it — so any C->U traffic counts as agent activity.
"""
import os
import socket
import sys
import threading
import time

LISTEN = ("0.0.0.0", 9223)
TARGET = ("127.0.0.1", 9222)
ACTIVITY_FILE = "/tmp/cdp-activity"
ACTIVITY_THROTTLE = 2.0  # seconds between file touches
_log_lock = threading.Lock()
_last_touch = 0.0


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with _log_lock:
        print(line, flush=True)
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def _mark_activity():
    """Throttled touch of the activity file (agent signal, spec 29)."""
    global _last_touch
    now = time.time()
    if now - _last_touch < ACTIVITY_THROTTLE:
        return
    _last_touch = now
    try:
        with open(ACTIVITY_FILE, "w") as f:
            f.write(str(int(now)))
    except OSError as e:
        log(f"activity touch failed: {e}")


def pipe(src, dst, tag):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                log(f"{tag} EOF {src.getpeername()[1]}->{dst.getpeername()[1]}")
                break
            dst.sendall(data)
            if tag.endswith("C->U"):
                _mark_activity()  # agent command flowing to the browser
    except OSError as e:
        log(f"{tag} OSError {e} {src.getpeername()[1]}->{dst.getpeername()[1]}")
    except Exception as e:
        log(f"{tag} EXC {type(e).__name__}: {e}")
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client, cid):
    try:
        upstream = socket.create_connection(TARGET, timeout=10)
        upstream.settimeout(None)  # CRITICAL: no idle timeout — a 10s idle
        # recv timeout here killed every long-lived CDP connection (~10s
        # after connect). Pure pipe: never time out.
    except OSError as e:
        log(f"conn {cid}: upstream fail {e}")
        client.close()
        return
    log(f"conn {cid}: open client={client.getpeername()} upstream={upstream.getpeername()}")
    t1 = threading.Thread(target=pipe, args=(client, upstream, f"conn {cid} C->U"), daemon=True)
    t2 = threading.Thread(target=pipe, args=(upstream, client, f"conn {cid} U->C"), daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()
    log(f"conn {cid}: closed")
    try:
        client.close()
        upstream.close()
    except OSError:
        pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(32)
    log("relay listening on 0.0.0.0:9223")
    cid = 0
    while True:
        conn, _ = srv.accept()
        cid += 1
        threading.Thread(target=handle, args=(conn, cid), daemon=True).start()


if __name__ == "__main__":
    main()
