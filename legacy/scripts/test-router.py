#!/usr/bin/env python3
"""Local functional test for router-v2-v3.py (spec 31) with a fake slot.

CB_AGENT_SLOTS=0 → only slot-1 is in the human pool. Fake slot-1:
  UI 127.0.0.1:19081 (router SLOT_PORT), restart API 127.0.0.1:9230
  (router hardcodes slot-1:9230 for /wake /suspend /identify — /etc/hosts
  maps slot-1 → 127.0.0.1).

Spec 31 test plan:
  A gets slot + Open Browser landing page (no neko login)
  B queues (queue page, position 1)
  A expiry (CB_HUMAN_MAX_SESSION_MIN≈5s) → reaper suspends → B offered →
    active + Open Browser button → clicks → proxied slot UI
  A returns after expiry → queue page (NOT login, NOT landing)
  Agent API: POST/GET/DELETE /queue, bad token, fleet status depth
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
import http.server

ROUTER_PORT = 18081
FAKE_UI, FAKE_RESTART = 19081, 9230
ST = "/tmp/router31-test-state.json"

class FakeSlot:
    def __init__(self):
        self.wakes = 0
        self.suspends = 0
        self.stale_suspend = False  # spec45: suspend no-op leaves chrome live
        self.rescues = 0  # spec 39: /restart-neko calls
        self.rescue_fail = False  # spec 39: simulate a failing slot rescue
        self.user = None
        self.notify_on_suspend = True  # False → simulate stuck release latch
        self.last_email = None  # Remote-Email header seen on the slot UI fetch
        # Spec 48: URLs the router asked us to open in the kiosk (via
        # restart-api /open-url) — landing ?goto= and session /kiosk/open.
        self.open_urls = []
        # Spec 45: mirror real slot semantics — /wake starts chrome (and
        # clears the suspended flag), /suspend stops it (and sets it).
        self.chrome_running = False
        self._http = None
        self._restart = None
        # Spec 51: fail the next index (UI) fetch with a 503 like a
        # respawning title-proxy; the router must retry, not raw-fallback.
        self.fail_next_index = False
        self.index_fetches = 0
        # Spec 77: owner-bound boot hint — mirrors restart-api /health's
        # pending_archive_owner. Set by the test to simulate a slot that
        # booted with an archive but no owner; cleared on /wake (the real
        # restart-api clears it once the slot is bound — one-shot per boot).
        self.pending_archive_owner = None

    def start(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(slf):
                self.last_email = slf.headers.get("Remote-Email")
                if self.fail_next_index:
                    self.fail_next_index = False
                    self.index_fetches += 1
                    slf.send_response(503)
                    slf.send_header("Content-Length", "0")
                    slf.end_headers()
                    return
                self.index_fetches += 1
                body = (b"<html><title>neko-slot1</title>"
                        b"<body>fake neko UI slot 1</body></html>")
                slf.send_response(200)
                slf.send_header("Content-Type", "text/html")
                slf.send_header("Content-Length", str(len(body)))
                slf.end_headers()
                slf.wfile.write(body)
            def log_message(slf, *a):
                pass
        class R(http.server.BaseHTTPRequestHandler):
            def do_GET(slf):
                if slf.path == "/health":
                    data = json.dumps({"ok": True, "name": "slot-1",
                                       "suspended": not self.chrome_running,
                                       "cdp_ok": self.chrome_running,
                                       "programs": {"google-chrome":
                                           "RUNNING" if self.chrome_running else "STOPPED"},
                                       "user": self.user,
                                       "pending_archive_owner":
                                           self.pending_archive_owner}).encode()
                    slf.send_response(200)
                    slf.send_header("Content-Type", "application/json")
                    slf.send_header("Content-Length", str(len(data)))
                    slf.end_headers()
                    slf.wfile.write(data)
                else:
                    slf.send_response(404); slf.end_headers()
            def do_POST(slf):
                n = int(slf.headers.get("Content-Length") or 0)
                raw = slf.rfile.read(n) if n else b""
                body = json.loads(raw) if raw.strip() else {}
                if slf.path == "/wake":
                    self.wakes += 1
                    self.user = body.get("user")
                    self.chrome_running = True
                    # Mirrors restart-api set_slot_user: binding an owner
                    # consumes the one-shot boot hint.
                    self.pending_archive_owner = None
                    print(f"[FAKESLOT] wake user={self.user} chrome={self.chrome_running} wakes={self.wakes}", flush=True)
                    resp = {"ok": True, "user": self.user}
                elif slf.path == "/suspend":
                    self.suspends += 1
                    if not self.stale_suspend:
                        self.chrome_running = False
                    print(f"[FAKESLOT] suspend stale={self.stale_suspend} chrome={self.chrome_running} suspends={self.suspends}", flush=True)
                    resp = {"ok": True, "user": self.user, "suspended": True}
                    # Real restart-api POSTs back to the router (release).
                    if self.notify_on_suspend and self.user:
                        try:
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{ROUTER_PORT}/fleet/release",
                                data=json.dumps({"user": self.user}).encode(),
                                method="POST",
                                headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req, timeout=5).read()
                        except Exception as e:
                            print("fake release failed:", e)
                        self.user = None
                elif slf.path == "/release":
                    # Spec 32: mirrors restart-api /release (tab bar Exit) —
                    # same teardown as suspend, but the router archive is
                    # labelled reason=released. A released slot is no longer
                    # Chrome-ready; the next owner must exercise /wake and
                    # pass the owner-bound readiness barrier.
                    self.suspends += 1
                    self.chrome_running = False
                    resp = {"ok": True, "user": self.user, "reason": "released"}
                    if self.notify_on_suspend and self.user:
                        try:
                            req = urllib.request.Request(
                                f"http://127.0.0.1:{ROUTER_PORT}/fleet/release",
                                data=json.dumps({"user": self.user,
                                                 "reason": "released"}).encode(),
                                method="POST",
                                headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req, timeout=5).read()
                        except Exception as e:
                            print("fake release failed:", e)
                        self.user = None
                elif slf.path == "/identify":
                    self.user = body.get("user")
                    resp = {"ok": True}
                elif slf.path == "/restart-neko":
                    # Spec 39: mirrors restart-api /restart-neko. A failing
                    # slot returns ok:false (router → 502).
                    if self.rescue_fail:
                        resp = {"ok": False, "error": "simulated failure"}
                    else:
                        self.rescues += 1
                        resp = {"ok": True, "detail": "neko: started"}
                elif slf.path == "/open-url":
                    # Spec 48: mirrors restart-api /open-url — the router
                    # asks the kiosk to open a surface (session pill /
                    # landing ?goto=). Record it for the assertions.
                    self.open_urls.append(body.get("url", ""))
                    resp = {"ok": True, "opened": True}
                else:
                    resp = {"ok": False}
                data = json.dumps(resp).encode()
                slf.send_response(200)
                slf.send_header("Content-Type", "application/json")
                slf.send_header("Content-Length", str(len(data)))
                slf.end_headers()
                slf.wfile.write(data)
            def log_message(slf, *a):
                pass
        class ReuseSrv(http.server.ThreadingHTTPServer):
            allow_reuse_address = True
            daemon_threads = True
        self._http = ReuseSrv(("127.0.0.1", FAKE_UI), H)
        self._restart = ReuseSrv(("127.0.0.1", FAKE_RESTART), R)
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        threading.Thread(target=self._restart.serve_forever, daemon=True).start()

    def stop(self):
        for s in (self._http, self._restart):
            if s:
                s.shutdown()
                s.server_close()
        self._http = self._restart = None


def start_router(extra_env=None):
    # Guarantee this router is the ONLY live one and the state file is
    # not being rewritten by a leaked process from a prior (possibly
    # crashed) run before Popen (no state wipe here — callers seed ST).
    _kill_leftover_routers()
    env = dict(os.environ)
    env.update({
        "ROUTER_PORT": str(ROUTER_PORT),
        "ROUTER_STATE": ST,
        "N_SLOTS": "2",
        "AUTO_CREATE_SESSIONS": "true",
        "CB_HUMAN_SLOTS": "1",
        "CB_AGENT_SLOTS": "0",
        "CB_HUMAN_MAX_SESSION_MIN": "0.08",
        "CB_AGENT_MAX_SESSION_MIN": "240",
        "CB_QUEUE_POLL_INTERVAL_S": "1",
        "CB_REAPER_INTERVAL_S": "1",
        "CB_OFFER_GRACE_S": "8",
        "CB_QUEUE_SHOW_EMAILS": "true",
        "CB_ADMIN_EMAILS": "",
        "CB_AGENT_TOKEN": "test-token",
        "NEKO_PASSWORD": "neko",
        "IDENTIFY_SWEEP_INTERVAL": "30",
        "SLOT_PORT": str(FAKE_UI),
        "FILES_PORT": str(FAKE_UI),
        "SLOT_API_PORT": str(FAKE_RESTART),
        "CB_RESET_AFTER": "3",
        "CB_RESET_COOLDOWN_S": "0.5",
    })
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "router-bootstrap-w31.py")],
        env=env, stdout=open("/tmp/spec45-router.log", "a"), stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    # Readiness wait: the router parses ~3 MB of source + binds before
    # serving; on a loaded box a fixed 1.5 s sleep in the caller races the
    # boot (seen 2026-08-28: Connection refused at the first poll right
    # after start_router). Poll until the port answers (or proc dies).
    deadline = time.time() + 12
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"router subprocess exited early rc={proc.returncode}")
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{ROUTER_PORT}/fleet/status")
            with urllib.request.urlopen(req, timeout=2) as r:
                r.read()
            break  # any HTTP response (even 4xx) proves the server is up
        except urllib.error.HTTPError:
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("router did not become ready in 12s")
    return proc


def add_hosts():
    pass  # handled by the bootstrap monkeypatch


def _kill_leftover_routers():
    """A crashed prior run can leave router-bootstrap.py alive holding
    ROUTER_PORT and REWRITING /tmp/router31-test-state.json — which then
    clobbers a freshly seeded state mid-run (seen 2026-08-28: the seeded
    spike-user session vanished and the dup-ids / expired-offer /
    offer_backed_off assertions then read the LEFTOVER router's state).
    Kill every one before starting a new router, and at run start."""
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "router-bootstrap.py"], text=True)
        for pid in out.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass
    except Exception:
        pass
    time.sleep(0.3)


def http_get(path, email=None):
    req = urllib.request.Request(f"http://127.0.0.1:{ROUTER_PORT}{path}")
    req.add_header("Host", "cloudbrowser.dev01.pmo.city")
    if email:
        req.add_header("Remote-Email", email)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), dict(e.headers)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_get_noredir(path, email=None):
    """GET without following redirects — returns status/location/headers."""
    req = urllib.request.Request(f"http://127.0.0.1:{ROUTER_PORT}{path}")
    req.add_header("Host", "cloudbrowser.dev01.pmo.city")
    req.add_header("Connection", "keep-alive")
    if email:
        req.add_header("Remote-Email", email)
    try:
        r = urllib.request.build_opener(_NoRedirect()).open(req, timeout=5)
        headers = dict(r.headers)
        # Reading to EOF is intentional: this test catches a redirect whose
        # HTTP/1.1 response has no framing and leaves the browser loading.
        r.read()
        return r.status, r.headers.get("Location"), headers, False
    except urllib.error.HTTPError as e:
        headers = dict(e.headers)
        try:
            e.read()
            return e.code, e.headers.get("Location"), headers, False
        except (TimeoutError, socket.timeout):
            return e.code, e.headers.get("Location"), headers, True


def raw_active_reload(email):
    """Probe the active reload over a raw keep-alive HTTP/1.1 socket."""
    sock = socket.create_connection(("127.0.0.1", ROUTER_PORT), timeout=5)
    try:
        sock.sendall((
            "GET / HTTP/1.1\r\n"
            "Host: cloudbrowser.dev01.pmo.city\r\n"
            f"Remote-Email: {email}\r\n"
            "Connection: keep-alive\r\n\r\n"
        ).encode())
        sock.settimeout(2)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        headers = {}
        lines = head.decode("latin1").split("\r\n")
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()
        expected = int(headers.get("content-length", "0"))
        while len(body) < expected:
            chunk = sock.recv(4096)
            if not chunk:
                break
            body += chunk
        try:
            extra = sock.recv(1)
            saw_eof = extra == b""
        except socket.timeout:
            saw_eof = False
        return lines[0] if lines else "", headers, len(body), saw_eof
    finally:
        sock.close()


def raw_get_close(path, email=None):
    """Send one request with Connection: close and return the response."""
    sock = socket.create_connection(("127.0.0.1", ROUTER_PORT), timeout=5)
    try:
        lines = [
            f"GET {path} HTTP/1.1",
            "Host: cloudbrowser.dev01.pmo.city",
            "Connection: close",
        ]
        if email:
            lines.append(f"Remote-Email: {email}")
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        sock.settimeout(5)
        chunks = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        sock.close()


def http_post(path, body, token=None, email=None):
    req = urllib.request.Request(f"http://127.0.0.1:{ROUTER_PORT}{path}",
                                 data=json.dumps(body).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    req.add_header("Host", "cloudbrowser.dev01.pmo.city")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if email:
        req.add_header("Remote-Email", email)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read().decode()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, {"_raw": raw}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw}


def fleet():
    st, body, _ = http_get("/fleet/status")
    return json.loads(body)


def main():
    add_hosts()
    try:
        os.unlink(ST)
    except OSError:
        pass
    slot = FakeSlot()
    slot.start()
    proc = start_router()
    time.sleep(1.5)
    passed, failed = [], []
    def check(name, cond, detail=""):
        (passed if cond else failed).append(name)
        print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))

    try:
        st, body, _ = http_get("/", email="a@x.pro")
        check("A: landing page + Open Browser button, no login",
              st == 200 and "Open Browser" in body and "pwd=" in body
              and "PLEASE LOG IN" not in body and "usr=" in body)
        check("A: landing title = CloudBrowser: <email> + PMO City favicon "
              "(Tigo 2026-08-22: title convention + favicon not the Neko cat)",
              "<title>CloudBrowser: a@x.pro</title>" in body
              and "rel=\"icon\" type=\"image/svg+xml\"" in body
              and "data:image/svg+xml;base64," in body,
              body[body.find("<title>"):body.find("<title>") + 200])
        check("spec48 rev2: landing pills — CloudFiles + Secrets are ALWAYS "
              "plain main-browser links (target=_blank, downloadable on the "
              "main computer); ONLY the GrantHub Shared pill enters the "
              "kiosk via ?goto= on the neko entry (Tigo 2026-08-23)",
              "/?pwd=neko&usr=a%40x.pro&goto=" in body
              and "goto=https%3A%2F%2Fcloudbrowser.dev01.pmo.city%2Fconnect"
              in body
              and 'href="https://cloudfiles.dev01.pmo.city/" target="_blank"'
              in body
              and 'href="https://secrets.pmo.city/" target="_blank"' in body
              and "goto=https%3A%2F%2Fcloudfiles.dev01.pmo.city%2F" not in body
              and "goto=https%3A%2F%2Fsecrets.pmo.city%2F" not in body,
              body[body.find("goto=") - 100:body.find("goto=") + 380])

        st, ms, _ = http_get("/fleet/my-status", email="a@x.pro")
        ms = json.loads(ms)
        check("my-status: active while in session",
              st == 200 and ms.get("state") == "active", json.dumps(ms))

        st, wbody, _ = http_get("/?pwd=neko&usr=a%40x.pro", email="a@x.pro")
        check("pwd-root: neko index with watchdog injected",
              st == 200 and "CB session watchdog" in wbody
              and "fake neko UI" in wbody
              and "neko-connect" in wbody and "open_url" in wbody,
              wbody[:200])

        # Active-session reload (Tigo 2026-08-22): neko strips ?pwd/usr from
        # the URL after auto-login, so a plain reload of "/" must jump back
        # into the live session (302 → ?pwd=&usr=), NOT land on the
        # "Open Browser" landing page.
        st302, loc, hdr302, timed_out = http_get_noredir("/", email="a@x.pro")
        check("active reload of / → 302 into session (no landing detour)",
              st302 == 302 and loc == "/?pwd=neko&usr=a%40x.pro",
              f"status={st302} location={loc!r}")
        check("active reload redirect is explicitly framed and closes",
              not timed_out and hdr302.get("Content-Length") == "0"
              and hdr302.get("Connection", "").lower() == "close",
              f"headers={hdr302} timed_out={timed_out}")
        raw_status, raw_headers, raw_body_len, raw_eof = raw_active_reload(
            "a@x.pro")
        check("active reload raw HTTP/1.1 response terminates",
              raw_status == "HTTP/1.1 302 Found"
              and raw_headers.get("content-length") == "0"
              and raw_headers.get("connection", "").lower() == "close"
              and raw_body_len == 0 and raw_eof,
              f"status={raw_status!r} headers={raw_headers} "
              f"body_len={raw_body_len} eof={raw_eof}")

        # Query strings can contain the internal Neko auto-login password.
        # Capture the handler log and assert that it records only the path,
        # never the raw query string or the password value.
        log_before = os.path.getsize("/tmp/spec45-router.log") \
            if os.path.exists("/tmp/spec45-router.log") else 0
        raw_get_close(
            "/?pwd=secret-test-value&usr=a%40x.pro", email="a@x.pro")
        with open("/tmp/spec45-router.log", encoding="utf-8") as fh:
            fh.seek(log_before)
            log_text = fh.read()
        check("router logs redact active-reload query strings",
              "secret-test-value" not in log_text
              and "pwd=" not in log_text
              and "GET / user=a@x.pro" in log_text,
              repr(log_text[-300:]))

        # Re-entry must KEEP a healthy in-flight clock: refreshing it on
        # every reload would reset the session limit and push every queued
        # user's ETA back up (Tigo 2026-08-22: after take-over everyone
        # reset to ~30 min). Only a STALE clock (redeploy-surviving /
        # clock skew) is refreshed — covered in the legacy-state section.
        try:
            sa0 = json.loads(open(ST).read())["sessions"]["a@x.pro"]["started_at"]
        except Exception:
            sa0 = None
        time.sleep(1.2)
        st, wb, _ = http_get("/?pwd=neko&usr=a%40x.pro", email="a@x.pro")
        time.sleep(0.3)  # allow the state flush
        sa1 = None
        try:
            sa1 = json.loads(open(ST).read())["sessions"]["a@x.pro"]["started_at"]
        except Exception:
            pass
        check("re-entry keeps healthy started_at (queued ETA not reset)",
              st == 200 and "fake neko UI" in wb
              and sa0 is not None and sa1 is not None
              and abs(sa1 - sa0) < 1.0,
              f"sa0={sa0} sa1={sa1}")
        check("pwd-root forwards Remote-Email to slot (session header email + title)",
              slot.last_email == "a@x.pro", f"last_email={slot.last_email!r}")

        # Spec 32/41 (2026-08-22, Tigo): Exit button → slot /release → the
        # router archives the session reason=released and frees the slot.
        # Spec 41: released archives do NOT auto-wake — the releaser
        # re-queues FIFO and the freed slot is offered to the queue head
        # (old spec-32 "reclaim instantly" exploit removed).
        req = urllib.request.Request(
            f"http://127.0.0.1:{FAKE_RESTART}/release", method="POST",
            data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            check("spec32: slot /release → 200", r.status == 200, str(r.status))
        time.sleep(0.6)  # allow the release notify to land
        f2 = fleet()
        check("spec32: released → archived reason=released, slot freed",
              f2["archives"].get("a@x.pro") == "released"
              and "a@x.pro" not in f2["users"]
              and "1" not in f2["slots"],
              json.dumps({k: f2[k] for k in ("users", "slots", "archives")}))
        st, ms2, _ = http_get("/fleet/my-status", email="a@x.pro")
        ms2 = json.loads(ms2)
        check("spec32: my-status = released (watchdog bounce state)",
              st == 200 and ms2.get("state") == "released", json.dumps(ms2))
        # Spec 41 re-entry with an EMPTY queue: the released archive never
        # wakes (only reason=idle does), but auto-create grants a FRESH
        # session — the accepted spec-32 reset-clock exploit, harmless with
        # nobody queued. (With waiters, the FIFO guard forces the queue page;
        # verified separately in the spec-41 D/E scenario below.)
        st, lb, _ = http_get("/", email="a@x.pro")
        check("spec41: released + empty queue → fresh session (landing page)",
              st == 200 and "Your browser session is ready" in lb,
              f"status={st}")
        st, ms3, _ = http_get("/fleet/my-status", email="a@x.pro")
        ms3 = json.loads(ms3)
        check("spec41: released + empty queue → auto-create (active)",
              st == 200 and ms3.get("state") == "active", json.dumps(ms3))
        # Stale-notify guard (spec 32): a release POST for a user the router
        # already released (slot carrying a stale .slot-user.json after the
        # self-heal force-release) must NOT overwrite the archive reason.
        st, rb = http_post("/fleet/release", {"user": "spike-stale@x.pro",
                                              "reason": "released"})
        check("spec32: stale notify for unknown user → 200",
              st == 200, f"status={st} body={rb}")
        # Re-release A: release A again (A is active on slot 1 after the
        # spec-41 auto-create re-entry) with reason=released, then a SECOND
        # stale notify with reason=idle must keep the existing "released"
        # archive.
        req = urllib.request.Request(
            f"http://127.0.0.1:{FAKE_RESTART}/release", method="POST",
            data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            check("spec32: slot /release #2 → 200", r.status == 200,
                  str(r.status))
        time.sleep(0.6)
        http_post("/fleet/release", {"user": "a@x.pro", "reason": "idle"})
        time.sleep(0.3)
        f3 = fleet()
        check("spec32: stale notify does not overwrite archive reason",
              f3["archives"].get("a@x.pro") == "released",
              json.dumps(f3["archives"]))

        # Spec 65 (2026-08-25): user-initiated release from the client
        # page top bar. Router /session/release (Remote-Email-keyed,
        # tinyauth-appended) forwards to the owner slot's restart-api
        # /release; the slot notify pops the router state
        # (reason=released, same semantics as the tab-bar Exit).
        st, lb, _ = http_get("/", email="a@x.pro")
        check("spec65: re-enter A for the release test",
              st == 200 and "Your browser session is ready" in lb,
              f"status={st}")
        st, jb = http_post("/session/release", {}, email="a@x.pro")
        jj = jb if isinstance(jb, dict) else {}
        check("spec65: /session/release → 200 ok",
              st == 200 and jj.get("ok") is True,
              f"status={st} body={str(jb)[:120]}")
        time.sleep(0.6)  # allow the slot release notify to land
        f65 = fleet()
        check("spec65: top-bar release → archived reason=released, slot freed",
              f65["archives"].get("a@x.pro") == "released"
              and "a@x.pro" not in f65["users"],
              json.dumps({k: f65[k] for k in ("users", "slots", "archives")}))
        st, jb = http_post("/session/release", {}, email=None)
        check("spec65: no Remote-Email → 401", st == 401, f"status={st}")
        st, jb = http_post("/session/release", {}, email="ghost@x.pro")
        check("spec65: no active session → 400", st == 400, f"status={st}")
        # Restore the pre-conditions the downstream tests expect (A active
        # on slot 1 when B enqueues). Spec 41: released + empty queue →
        # auto-create fresh session (no archive wake, no offer needed).
        st, lb, _ = http_get("/", email="a@x.pro")
        check("spec41: restore — A auto-creates on the freed slot",
              st == 200 and "Your browser session is ready" in lb,
              f"status={st}")
        st, ms4, _ = http_get("/fleet/my-status", email="a@x.pro")
        ms4 = json.loads(ms4)
        check("spec41: restore — A active (pre-cond for downstream B tests)",
              st == 200 and ms4.get("state") == "active", json.dumps(ms4))

        st, body, _ = http_get("/", email="b@x.pro")
        check("B: queue page (no slot)", st == 200 and "Your position" in body, body[:120])
        check("B: queue page title = CloudBrowser: <email> + PMO City favicon "
              "(Tigo 2026-08-22: was 'CloudBrowser — queue' + no favicon)",
              "<title>CloudBrowser: b@x.pro</title>" in body
              and "rel=\"icon\" type=\"image/svg+xml\"" in body
              and "data:image/svg+xml;base64," in body,
              body[body.find("<title>"):body.find("<title>") + 200])
        check("B: queue page top bar (spec 48 rev2, Tigo 2026-08-23) = brand + "
              "CloudFiles + Secrets ALWAYS plain main-browser links "
              "(target=_blank, no pending-goto intent); GrantHub Not Shared "
              "hidden here (no kiosk to capture in yet)",
              st == 200 and "class=\"header\"" in body
              and "C</b>loud<b>B</b>rowser" in body
              and "data:image/svg+xml;base64" in body
              and "📁 CloudFiles" in body and "b@x.pro" in body
              and "🔒 Secrets" in body and "🔗 Not Shared" not in body
              and 'href="https://cloudfiles.dev01.pmo.city/" target="_blank"'
              in body
              and 'href="https://secrets.pmo.city/" target="_blank"' in body
              and "data-goto=" not in body
              and "/queue/goto" not in body
              and "fa-bars" not in body, body[:600])
        # Spec 48 rev2: the queue page has NO pending-goto machinery — the
        # pill click is a plain main-browser link (rev1's /queue/goto intent
        # store was removed: a queued user's intent could ride ANOTHER
        # user's offer-take; the surface must never be forced into a kiosk).
        st, gb = http_post("/queue/goto",
                           {"url": "https://secrets.pmo.city/"},
                           email="b@x.pro")
        check("spec48 rev2: POST /queue/goto is GONE (404/queue page, no "
              "pending-intent JSON)",
              not (isinstance(gb, dict) and gb.get("ok")),
              f"status={st} body={str(gb)[:160]}")

        # --- Spec 48 (capture-surface UX) --------------------------------
        # Entry with ?goto= (landing-pill click) → forwarded to the slot's
        # restart-api /open-url (fire-and-forget thread) so the kiosk opens
        # the surface.
        slot.open_urls.clear()
        stg, gbody, _ = http_get(
            "/?pwd=neko&usr=a%40x.pro&goto=" + urllib.parse.quote(
                "https://secrets.pmo.city/", safe=""), email="a@x.pro")
        time.sleep(1.0)
        check("spec48: entry ?goto= opens the surface in the kiosk",
              stg == 200 and "https://secrets.pmo.city/" in slot.open_urls,
              f"status={stg} open_urls={slot.open_urls}")
        # Entry with a non-whitelisted goto → ignored (kiosk untouched).
        slot.open_urls.clear()
        http_get("/?pwd=neko&usr=a%40x.pro&goto=" + urllib.parse.quote(
            "https://evil.example.com/", safe=""), email="a@x.pro")
        time.sleep(1.0)
        check("spec48: non-whitelisted ?goto= is ignored",
              slot.open_urls == [], f"open_urls={slot.open_urls}")
        # Session-page pills: POST /kiosk/open → active slot's restart-api.
        slot.open_urls.clear()
        st, kb = http_post("/kiosk/open?url=" + urllib.parse.quote(
            "https://secrets.pmo.city/", safe=""), {}, email="a@x.pro")
        check("spec48: /kiosk/open opens the surface in the kiosk",
              st == 200 and kb.get("ok") and kb.get("slot") == 1
              and "https://secrets.pmo.city/" in slot.open_urls,
              f"status={st} body={kb} open_urls={slot.open_urls}")
        st, kb = http_post("/kiosk/open?url=" + urllib.parse.quote(
            "/connect", safe=""), {}, email="a@x.pro")
        check("spec50: /kiosk/open absolutizes same-origin paths"
              " (/connect → https://cloudbrowser.dev01.pmo.city/connect)",
              st == 200 and kb.get("ok")
              and "https://cloudbrowser.dev01.pmo.city/connect"
              in slot.open_urls,
              f"status={st} body={kb} open_urls={slot.open_urls}")
        st, kb = http_post("/kiosk/open?url=" + urllib.parse.quote(
            "https://evil.example.com/", safe=""), {}, email="a@x.pro")
        check("spec48: /kiosk/open rejects non-whitelisted URLs",
              st == 400 and not kb.get("ok"), f"status={st} body={kb}")
        st, kb = http_post("/kiosk/open?url=" + urllib.parse.quote(
            "https://secrets.pmo.city/", safe=""), {}, email="nobody@x.pro")
        check("spec48: /kiosk/open 409 when the user has no active slot",
              st == 409 and not kb.get("ok"), f"status={st} body={kb}")
        noem_req = urllib.request.Request(
            f"http://127.0.0.1:{ROUTER_PORT}/kiosk/open?url="
            + urllib.parse.quote("https://secrets.pmo.city/", safe=""),
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(noem_req, timeout=5) as r:
                st_no = r.status
        except urllib.error.HTTPError as e:
            st_no = e.code
        check("spec48: /kiosk/open 401 without Remote-Email",
              st_no == 401, f"status={st_no}")

        # Spec 37 §2.5 (LOCKED): CloudFiles host never acquires a slot and
        # never queues — proxied straight to a slot's downloads surface.
        cf_req = urllib.request.Request(f"http://127.0.0.1:{ROUTER_PORT}/")
        cf_req.add_header("Host", "cloudfiles.dev01.pmo.city")
        cf_req.add_header("Remote-Email", "c@x.pro")
        try:
            with urllib.request.urlopen(cf_req, timeout=5) as r:
                cf_st, cf_body = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            cf_st, cf_body = e.code, e.read().decode()
        check("CloudFiles: proxied to slot surface (no queue page)",
              cf_st == 200 and "fake neko UI" in cf_body, cf_body[:200])
        j = fleet()
        check("CloudFiles: visitor NOT enqueued",
              all(e.get("email") != "c@x.pro" for e in j.get("queue", [])),
              str(j.get("queue"))[:200])

        st, j, _ = http_get("/queue/status", email="b@x.pro")
        j = json.loads(j)
        check("B status: waiting pos>=1", st == 200 and j.get("status") == "waiting"
              and j.get("position", 0) >= 1, json.dumps(j))
        check("B status: active_humans shows holder (a@x.pro)",
              st == 200 and "a@x.pro" in (j.get("active_humans") or []),
              json.dumps(j.get("active_humans")))
        check("B status: own email listed with pos 1 (numbered queue, not top-right only)",
              st == 200 and "b@x.pro" not in (j.get("active_humans") or [])
              and any(w.get("email") == "b@x.pro" and w.get("pos") == 1
                      for w in (j.get("waiting") or [])),
              json.dumps({"w": j.get("waiting"), "a": j.get("active_humans")}))

        # ETA must be TIME-BASED and decreasing (Tigo 2026-08-22): the old
        # statistical ETA (pos/coming × history median) was a constant that
        # never moved on reload. Now it tracks the active session's
        # remaining time, so consecutive polls show a smaller wait.
        st, j1, _ = http_get("/queue/status", email="b@x.pro")
        j1 = json.loads(j1)
        time.sleep(2)
        st, j2, _ = http_get("/queue/status", email="b@x.pro")
        j2 = json.loads(j2)
        e1, e2 = j1.get("eta_s", 0), j2.get("eta_s", 0)
        check("B ETA: time-based and decreasing across polls",
              e1 > e2 >= 0 and e1 <= 3 * 60,
              f"eta1={e1}s eta2={e2}s (MAX=4.8s, grace=10s)")

        # Spec 51: the slot's title-proxy can respawn right after a wake —
        # first index fetch 503s; the router must retry once and still serve
        # the watchdog-injected session page (no error page). Placed after
        # the ETA check: the retry's 0.8s sleep shifts wall-clock timing,
        # which a razor-thin ETA assertion above cannot tolerate.
        slot.fail_next_index = True
        slot.index_fetches = 0
        st51, b51, _ = http_get("/", email="a@x.pro")
        check("spec51: router retries a failing slot index fetch "
              "(503 → retry → watchdog-injected page, not an error)",
              st51 == 200 and slot.index_fetches == 2
              and "watchdog" in b51 and "neko-slot1" in b51,
              f"status={st51} index_fetches={slot.index_fetches} "
              f"len={len(b51)}")

        st, j = http_post("/queue", {"caller": "agent-x"}, token="test-token")
        check("Agent POST /queue -> 202 waiting", st == 202 and j.get("status") == "waiting", f"{st} {j}")
        qid = j.get("queue_id")

        st, j, _ = http_get(f"/queue/{qid}")
        j = json.loads(j)
        check("Agent GET /queue/<id>", st == 200 and j.get("status") == "waiting")

        st, j = http_post("/queue", {"caller": "x"}, token="nope")
        check("Agent POST bad token -> 401", st == 401)

        req = urllib.request.Request(f"http://127.0.0.1:{ROUTER_PORT}/queue/{qid}", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            check("Agent DELETE /queue/<id>", r.status == 200)

        j = fleet()
        check("Fleet status queueDepth + archives reasons",
              j.get("queueDepth", {}).get("human", 0) >= 1 and "archives" in j, str(j)[:200])

        time.sleep(6)  # A's ~5s session expires
        # Spec 36 §21 offer flow: when the slot frees the head is OFFERED
        # (status 'offered', slot reserved, clock NOT started) — not
        # instantly active. The user has CB_OFFER_GRACE_S to take it.
        offered = None
        d_offer = time.time() + 12
        while time.time() < d_offer:
            st, j, _ = http_get("/queue/status", email="b@x.pro")
            j = json.loads(j)
            if j.get("status") == "offered":
                offered = j
                break
            time.sleep(0.5)
        check("B offered (not active) after A expiry: open_url + ttl, not assigned",
              offered is not None
              and offered.get("status") == "offered"
              and offered.get("open_url")
              and offered.get("offer_ttl_s", 0) > 0
              and fleet().get("users", {}).get("b@x.pro") is None,
              json.dumps(offered))
        check("A archived reason=expired",
              fleet().get("archives", {}).get("a@x.pro") == "expired",
              str(fleet().get("archives")))
        st, qpage, _ = http_get("/", email="b@x.pro")
        check("queue page while offered: grace countdown replaces position",
              st == 200 and "Offer expires in" in qpage
              and "fmtCd" in qpage and "countdownEndsAt" in qpage,
              qpage[:200])
        st, ms2, _ = http_get("/fleet/my-status", email="a@x.pro")
        ms2 = json.loads(ms2)
        check("my-status: expired after max-duration (watchdog redirects)",
              st == 200 and ms2.get("state") == "expired", json.dumps(ms2))
        check("slot-1 suspended by reaper", slot.suspends >= 1, f"suspends={slot.suspends}")

        # Take the offer: the session clock starts NOW (take-over), so B
        # gets the full session limit — the queued ETA is not inflated by
        # an offer-time clock start.
        t_take = time.time()
        st, body, _ = http_get(offered["open_url"], email="b@x.pro")
        time.sleep(0.3)
        b_ses = None
        try:
            b_ses = json.loads(open(ST).read())["sessions"]["b@x.pro"]
        except Exception:
            pass
        check("B takes offer: active, clock starts at take-over",
              st == 200 and "fake neko UI" in body
              and fleet().get("users", {}).get("b@x.pro") == 1
              and b_ses is not None and abs(b_ses["started_at"] - t_take) < 2,
              f"ses={b_ses} t_take={t_take}")
        st, jb, _ = http_get("/queue/status", email="b@x.pro")
        jb = json.loads(jb)
        check("B status now active with open_url (no zombie)",
              jb.get("status") == "active" and jb.get("open_url")
              and not jb.get("offer_ttl_s"), json.dumps(jb))
        check("B active: session_ttl_s countdown present (>0)",
              jb.get("session_ttl_s", 0) > 0, json.dumps(jb))
        st, qpage2, _ = http_get("/", email="a@x.pro")
        check("queue page ships countdown wiring (offered + active labels)",
              st == 200 and "Session ends in" in qpage2
              and "Offer expires in" in qpage2 and "fmtCd" in qpage2,
              qpage2[:200])

        st, body, _ = http_get("/", email="a@x.pro")
        check("A re-queued after expiry (queue page, not login)",
              st == 200 and "Your position" in body, body[:120])

        # Regression (spec 31): releasing an active queue user (slot idle
        # suspend) must drop their queue entry — no stale "active" entry.
        st, j = http_post("/fleet/release", {"user": "b@x.pro"})
        time.sleep(1.5)
        j = fleet()
        check("release drops queue entry (no stale active)",
              all(e.get("email") != "b@x.pro"
                  for e in j.get("queue", []))
              and j.get("users", {}).get("b@x.pro") is None
              and j.get("archives", {}).get("b@x.pro") == "idle",
              str(j)[:300])

        # Regression (spec 31 reaper self-heal): a slot whose suspend
        # succeeds but whose release callback never lands (stuck _suspended
        # latch) must not wedge the fleet — the router force-releases the
        # expiring user after the grace period so the queue can advance.
        slot.notify_on_suspend = False  # simulate the stuck release latch
        st, j = http_post("/fleet/release", {"user": "b@x.pro"})  # free slot 1
        st, j, _ = http_get("/queue/status", email="c@x.pro")  # c joins queue
        j = json.loads(j)
        check("self-heal: c queued (freed slot offered by reaper)",
              st == 200 and j.get("status") in ("waiting", "offered"),
              json.dumps(j))
        # a@x.pro (re-queued first) is the head: a is offered, a takes it,
        # then a expires with the stuck latch → force-release. Then c is
        # offered; c takes it, expires, and is force-released too.
        # While a sits in the stuck grace (expiring but still assigned),
        # my-status must read "expired" and GET / must serve the queue
        # page — no landing page, no neko login flash.
        a_taken = False
        c_offered = False
        grace_seen = grace_root_ok = False
        d1 = time.time() + 35
        while time.time() < d1:
            j = fleet()
            if not a_taken:
                st_a, ja, _ = http_get("/queue/status", email="a@x.pro")
                try:
                    ja = json.loads(ja)
                except Exception:
                    ja = {}
                if ja.get("status") == "offered" and ja.get("open_url"):
                    http_get(ja["open_url"], email="a@x.pro")  # a takes it
                    a_taken = True
            if not grace_seen:
                st_a, ms_a, _ = http_get("/fleet/my-status", email="a@x.pro")
                try:
                    ms_a = json.loads(ms_a)
                except Exception:
                    ms_a = {}
                if ms_a.get("state") == "expired" and \
                        j.get("users", {}).get("a@x.pro") is not None:
                    grace_seen = True
                    st_r, body_r, _ = http_get("/", email="a@x.pro")
                    grace_root_ok = st_r == 200 and "Your position" in body_r
            if j.get("users", {}).get("a@x.pro") is None:
                st_c, jc, _ = http_get("/queue/status", email="c@x.pro")
                try:
                    jc = json.loads(jc)
                except Exception:
                    jc = {}
                if jc.get("status") == "offered" and jc.get("open_url"):
                    http_get(jc["open_url"], email="c@x.pro")  # c takes it
                    c_offered = True
            time.sleep(1)
        check("grace window: my-status=expired while user still assigned (watchdog bounces)",
              grace_seen, f"grace_seen={grace_seen} users={j.get('users')}")
        check("grace window: GET / serves queue page (no landing, no neko login)",
              grace_seen and grace_root_ok,
              f"grace_seen={grace_seen} root_ok={grace_root_ok}")
        released = None
        deadline = time.time() + 40
        while time.time() < deadline:
            j = fleet()
            if j.get("users", {}).get("c@x.pro") is None:
                released = j.get("archives", {}).get("c@x.pro")
                if released:
                    break
            time.sleep(2)
        check("self-heal: c force-released (expired) without slot callback",
              c_offered and released == "expired",
              f"c_offered={c_offered} released={released} "
              f"users={j.get('users')} archives={j.get('archives')}")

        # Regression (spec 36 §19): queue ids must survive restarts. The
        # legacy in-memory counter reset to 1 on restart and reused ids of
        # entries that survived in the persisted queue — the LIVE fleet had
        # TWO 'q-1' entries and _eta_for's id lookup handed both users
        # position 1. Boot must heal colliding ids and the sequence must
        # continue from the persisted value.
        proc.send_signal(signal.SIGTERM)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate()
        legacy = {
            "users": {"spike-user@aikumi.pro": 1},
            "slots": {"1": "spike-user@aikumi.pro"},
            "sessions": {"spike-user@aikumi.pro": {
                "slot": 1, "started_at": time.time() + 120, "tier": "human"}},
            "queue": [
                {"id": "q-1", "type": "human", "email": "montigaud@aikumi.pro",
                 "priority": 0, "enqueued_at": time.time() - 1000,
                 "status": "waiting", "offer_expires_at": None},
                {"id": "q-1", "type": "human", "email": "spike-user2@aikumi.pro",
                 "priority": 0, "enqueued_at": time.time() - 500,
                 "status": "waiting", "offer_expires_at": None},
                # Spec 36 §21: an offer that expired (grace elapsed, never
                # taken) must be swept back to WAITING at the BACK of the
                # queue on boot — one-shot chance, no zombie offers.
                {"id": "q-6", "type": "human", "email": "offer-lapsed@x.pro",
                 "priority": 0, "enqueued_at": time.time() - 50,
                 "status": "offered", "offer_expires_at": time.time() - 5,
                 "slot": 1},
            ],
            "archives": {}, "history": {},
        }
        with open(ST, "w") as f:
            json.dump(legacy, f)
        proc = start_router()
        time.sleep(1.5)
        st, body, _ = http_get("/queue/status", email="spike-user2@aikumi.pro")
        j = json.loads(body)
        ids = [e.get("id") for e in fleet().get("queue", [])]
        check("dup ids healed: unique after boot", len(ids) == len(set(ids)),
              str(ids))
        check("dup ids healed: second user gets pos 2",
              st == 200 and j.get("position") == 2
              and [w.get("pos") for w in j.get("waiting", [])][:2] == [1, 2],
              json.dumps(j))
        st, lo, _ = http_get("/queue/status", email="offer-lapsed@x.pro")
        lo = json.loads(lo)
        fq = fleet().get("queue", [])
        lapsed = next((e for e in fq if e.get("email") == "offer-lapsed@x.pro"), None)
        check("expired offer swept: back to waiting at the BACK of the queue",
              lapsed is not None and lapsed.get("status") == "waiting"
              and lapsed.get("enqueued_at", 0) > time.time() - 10
              and lo.get("status") == "waiting"
              and lo.get("position") == 3
              and not lo.get("open_url"),
              json.dumps({"entry": lapsed, "status": lo}))
        check("expired offer archived reason=offer_expired",
              fleet().get("archives", {}).get("offer-lapsed@x.pro")
              == "offer_expired",
              str(fleet().get("archives")))
        st, body, _ = http_get("/", email="c@x.pro")  # fresh enqueue
        time.sleep(0.3)
        fq = fleet().get("queue", [])
        ids2 = [e.get("id") for e in fq]
        check("fresh enqueue after restart gets unique id",
              len(ids2) == len(set(ids2)) and ids2
              and any(e.get("email") == "c@x.pro" for e in fq),
              str(ids2))

        # Stale-clock refresh (redeploy/skew case): the seeded state carries
        # spike-user's started_at in the FUTURE (clock skew). Re-entry must
        # refresh it — otherwise the reaper would stall or instantly expire.
        st, wb3, _ = http_get("/?pwd=neko&usr=spike-user%40aikumi.pro",
                              email="spike-user@aikumi.pro")
        time.sleep(0.3)
        sa = json.loads(open(ST).read())["sessions"]["spike-user@aikumi.pro"]["started_at"]
        check("stale (skewed) started_at refreshed on re-entry",
              st == 200 and "fake neko UI" in wb3
              and abs(time.time() - sa) < 3,
              f"sa={sa} now={time.time()}")

        # Regression (spec 36 §25): releasing an OFFERED-but-never-assigned
        # user (slot idle watchdog fires while the user still holds a
        # pending offer) must clear their offer_hold — otherwise the
        # reaper's per-slot guard (k in _offer_holds) refuses to offer the
        # slot and the whole queue strands behind a phantom hold.
        # Repro seen LIVE 2026-08-22: spike-user offered, never connected
        # (stale tab running pre-fix JS), slot idle watchdog POSTed
        # /fleet/release, and the queue stranded for 5+ min with
        # montigaud waiting, slot free, NO offer issued.
        seed = {
            "users": {}, "slots": {}, "sessions": {},
            "queue": [
                {"id": "q-r1", "type": "human", "email": "a@x.pro",
                 "priority": 0, "enqueued_at": time.time() - 50,
                 "status": "waiting", "offer_expires_at": None},
                {"id": "q-r2", "type": "human", "email": "b@x.pro",
                 "priority": 0, "enqueued_at": time.time() - 40,
                 "status": "waiting", "offer_expires_at": None},
            ],
            "archives": {}, "history": {},
        }
        proc.send_signal(signal.SIGTERM)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate()
        # write the seed AFTER the old router is dead (it saves state
        # continuously and could clobber the seed between write and kill)
        with open(ST, "w") as f:
            json.dump(seed, f)
        proc = start_router()
        time.sleep(1.5)  # bind grace, same as the other restart tests
        offered_r = None
        deadline = time.time() + 12
        while time.time() < deadline:
            st, jb, _ = http_get("/queue/status", email="a@x.pro")
            jb = json.loads(jb)
            if jb.get("status") == "offered":
                offered_r = jb
                break
            time.sleep(0.5)
        check("offer-hold release: head offered first",
              offered_r is not None and offered_r.get("status") == "offered"
              and offered_r.get("open_url"),
              str(offered_r))
        st, rel = http_post("/fleet/release", {"user": "a@x.pro"})
        check("offer-hold release: release accepted (idle)",
              st == 200 and rel.get("ok") is True
              and rel.get("reason") == "idle", json.dumps(rel))
        offered_b = None
        deadline = time.time() + 12
        while time.time() < deadline:
            st, jb, _ = http_get("/queue/status", email="b@x.pro")
            jb = json.loads(jb)
            if jb.get("status") == "offered":
                offered_b = jb
                break
            time.sleep(0.5)
        check("offer-hold release: next user offered (no phantom hold)",
              offered_b is not None and offered_b.get("open_url"),
              f"b_status={jb.get('status')} queue={fleet().get('queue')}")
        check("offer-hold release: released user archived idle + gone",
              fleet().get("archives", {}).get("a@x.pro") == "idle"
              and all(e.get("email") != "a@x.pro"
                      for e in fleet().get("queue", [])),
              json.dumps(fleet().get("archives")))

        # Regression (spec 36 §26): ETA sanity. Tigo 2026-08-22: queue page
        # showed "≈51 min" at position 2 with a 15-min session limit.
        # Two bugs: (1) busy=0 branch added the user's OWN future session
        # (pos 2 → 2×med instead of 1×med) and (2) med was NOT capped at the
        # current limit, so stale history from the 30-min era (25-38 min
        # durations) inflated every step. Seed history with 25-min-era
        # values and NO active session; b@x.pro at pos 2 must see
        # eta ≈ min(med, MAX)=4.8s (old code: 2×4.8=9.6s, or 3048s uncapped).
        seed = {
            "users": {}, "slots": {}, "sessions": {},
            "queue": [
                {"id": "q-e1", "type": "human", "email": "a@x.pro",
                 "priority": 0, "enqueued_at": time.time() - 50,
                 "status": "waiting", "offer_expires_at": None},
                {"id": "q-e2", "type": "human", "email": "b@x.pro",
                 "priority": 0, "enqueued_at": time.time() - 40,
                 "status": "waiting", "offer_expires_at": None},
            ],
            "archives": {},
            "history": {"human": [1500.0, 1600.0, 1700.0]},  # 25-28 min era
        }
        proc.send_signal(signal.SIGTERM)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate()
        with open(ST, "w") as f:
            json.dump(seed, f)
        proc = start_router()
        time.sleep(1.5)  # bind grace
        st, jb, _ = http_get("/queue/status", email="b@x.pro")
        jb = json.loads(jb)
        b_eta = jb.get("eta_s", -1)
        check("ETA busy=0: wait-to-open only (own session NOT counted) + med capped",
              jb.get("status") == "waiting" and 1 <= b_eta <= 6,
              f"status={jb.get('status')} eta={b_eta}s (MAX=4.8s; "
              f"old: 2×min(25.4min,MAX)=9.6s / uncapped 3048s)")

        # ---- Spec 39: wedged-neko auto-rescue ---------------------------
        # Restart with a long session limit so the rescue tests are immune
        # to the 4.8s test-expiry race. Watchdog escalation path: active
        # session whose neko is wedged (LOG IN persists, ?pwd= never
        # stripped) → POST /fleet/rescue → slot /restart-neko (app-only).
        # 401 auth, 429 cooldown, 502 slot fail, rescues in /fleet/status.
        proc.send_signal(signal.SIGTERM)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate()
        with open(ST, "w") as f:
            json.dump({"users": {}, "slots": {}, "archives": {}}, f)
        proc = start_router({"CB_HUMAN_MAX_SESSION_MIN": "5",
                             "CB_MAX_RESCUES": "5"})  # spec 54: budget high so
        # the classic spec39/40 escalation tests below (3 rescues) still pass
        time.sleep(1.5)  # bind grace
        st, jb, _ = http_get("/queue/status", email="r@x.pro")
        jb = json.loads(jb)
        check("spec39: r@x.pro acquires the free slot (active)",
              jb.get("status") == "active" and bool(jb.get("open_url")),
              str(jb))
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"})
        check("spec39: /fleet/rescue without Remote-Email → 401",
              st == 401 and not rj.get("ok"), json.dumps(rj))
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"},
                           email="nobody@x.pro")
        check("spec39: /fleet/rescue for non-active user → 401",
              st == 401 and not rj.get("ok"), json.dumps(rj))
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"},
                           email="r@x.pro")
        check("spec39: rescue fires → 200 + slot /restart-neko called",
              st == 200 and rj.get("ok") is True
              and rj.get("action") == "restart-neko" and slot.rescues == 1,
              json.dumps(rj))
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"},
                           email="r@x.pro")
        check("spec39: immediate second rescue → 429 cooldown",
              st == 429 and not rj.get("ok") and slot.rescues == 1,
              json.dumps(rj))
        st, fs, _ = http_get("/fleet/status")
        _resc = json.loads(fs).get("rescues", {}).get("r@x.pro")
        if isinstance(_resc, dict):  # spec 40: {ts, reason}
            _rval = _resc.get("ts", 0)
        else:
            _rval = _resc or 0
        check("spec39: /fleet/status surfaces rescues",
              _rval >= 1, fs[:200])
        time.sleep(1.0)  # cooldown (0.5 s) lapses
        slot.rescue_fail = True
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"},
                           email="r@x.pro")
        check("spec39: failing slot → 502, no cooldown recorded",
              st == 502 and not rj.get("ok") and slot.rescues == 1,
              json.dumps(rj))
        slot.rescue_fail = False
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"},
                           email="r@x.pro")
        check("spec39: rescue retries after failure → 200",
              st == 200 and rj.get("ok") is True and slot.rescues == 2,
              json.dumps(rj))
        st, jb, _ = http_get("/fleet/my-status", email="r@x.pro")
        check("spec39: active session unaffected by rescue (my-status)",
              json.loads(jb).get("state") == "active",
              jb[:200])
        # Spec 40: rescue carries a reason (stream-dead = blank-page wedge)
        time.sleep(1.0)  # cooldown lapses
        st, rj = http_post("/fleet/rescue",
                           {"requester": "watchdog", "reason": "stream-dead"},
                           email="r@x.pro")
        check("spec40: rescue with reason stream-dead → 200",
              st == 200 and rj.get("ok") is True and slot.rescues == 3,
              json.dumps(rj))
        st, fs, _ = http_get("/fleet/status")
        _r2 = json.loads(fs).get("rescues", {}).get("r@x.pro")
        check("spec40: /fleet/status records rescue reason",
              isinstance(_r2, dict) and _r2.get("reason") == "stream-dead"
              and _r2.get("ts", 0) >= 1, json.dumps(_r2))

        # ---- Spec 54: per-session rescue cap ---------------------------
        # The legacy cap assertions above are intentionally replaced by the
        # circuit-breaker contract: after the last permitted rescue, the
        # server must quarantine/release the broken assignment instead of
        # keeping it active until the normal TTL.
        proc.send_signal(signal.SIGTERM)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.communicate()
        with open(ST, "w") as f:
            json.dump({"users": {}, "slots": {}, "archives": {},
                       "queue": [], "sessions": {}, "history": {},
                       "rescue_at": {}, "queue_seq": 0}, f)
        slot.rescues = 0
        slot.user = None
        slot.chrome_running = False
        proc = start_router({"CB_HUMAN_MAX_SESSION_MIN": "5",
                             "CB_MAX_RESCUES": "1"})
        time.sleep(1.5)  # bind grace
        st, jb, _ = http_get("/queue/status", email="r@x.pro")
        jb = json.loads(jb)
        check("circuit: r@x.pro acquires the slot (active)",
              jb.get("status") == "active" and bool(jb.get("open_url")),
              str(jb))
        st, rj = http_post("/fleet/rescue", {"requester": "watchdog"},
                           email="r@x.pro")
        check("circuit: first rescue → restart-neko (budget 1/1)",
              st == 200 and rj.get("action") == "restart-neko"
              and slot.rescues == 1, json.dumps(rj))
        time.sleep(1.0)  # cooldown (0.5 s) lapses
        st, rj = http_post("/fleet/rescue",
                           {"requester": "watchdog", "reason": "stream-dead"},
                           email="r@x.pro")
        fs = fleet()
        check("circuit: rescue cap quarantines broken session",
              st == 200 and rj.get("action") in ("quarantine", "recovery")
              and "r@x.pro" not in fs.get("users", {})
              and fs.get("archives", {}).get("r@x.pro")
              in ("stream_dead_cap", "rescue_cap"),
              f"response={rj} fleet={fs}")
        st, jb, _ = http_get("/fleet/my-status", email="r@x.pro")
        check("circuit: quarantined session is not active",
              json.loads(jb).get("state") != "active", jb[:240])
        # Same request after teardown is idempotent and must not restart a
        # slot or create a duplicate queue/offer for the old owner.
        rescues_before = slot.rescues
        st, rj = http_post("/fleet/rescue",
                           {"requester": "watchdog", "reason": "stream-dead"},
                           email="r@x.pro")
        fs2 = fleet()
        check("circuit: repeated cap request cannot restart or resurrect",
              st == 401 and slot.rescues == rescues_before
              and "r@x.pro" not in fs2.get("users", {})
              and all(e.get("email") != "r@x.pro" for e in fs2.get("queue", [])),
              f"response={rj} fleet={fs2}")

        # The browser must apply the same finite rescue budget to stream-dead
        # and call the server-side quarantine transition before root bounce.
        # Use a fresh active owner so this check does not depend on queue poll
        # side effects from the prior teardown.
        st, jb, _ = http_get("/queue/status", email="r2@x.pro")
        jb = json.loads(jb)
        st, body, _ = http_get("/?pwd=neko&usr=r2%40x.pro", email="r2@x.pro")
        # Scope the assertion to the stream-dead branch itself: the terminal
        # stream-dead-cap fetch must come BEFORE the redirect back to root
        # (tell the server to quarantine, THEN bounce — never bounce into
        # the still-dead viewer). Using a bare body.find('location.href')
        # would match the earlier healthy-drop redirect, which has nothing
        # to do with the quarantine contract.
        _stream_b = body.find("if (streamDead())")
        _cap_f = body.find("stream-dead-cap", _stream_b)
        _redir_f = body.find('location.href = "/"', _cap_f)
        check("circuit: watchdog has stream-dead budget/quarantine branch",
              _stream_b >= 0 and "cb_rescues" in body
              and _cap_f > _stream_b and _redir_f > _cap_f,
              body[max(_stream_b, 0):_redir_f + 40])
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill(); out, _ = proc.communicate()
        slot.stop()
        print("\n===== router log tail =====")
        print("\n".join((out or "").splitlines()[-30:]))

    # B (2026-08-22, Tigo A+B): the raw-proxy FALLBACK must also inject
    # the watchdog into text/html responses. Tigo was stuck on the neko
    # LOG IN screen after expiry — his page never got the in-page
    # watchdog, so the extension-hosted watchdog (A) is the real fix and
    # this (B) closes the router's injection hole. In-process unit test
    # of _pipe_injected (router-independent; placed here so its runtime
    # cannot skew the session-clock timing checks above).
    import importlib.util as _ilu, socket as _sock

    def run_pipe(fake_resp):
        # up: (us, uc) — write fake into us, helper reads uc.
        # conn: (cs, cc) — helper writes cc, we read cs.
        us, uc = _sock.socketpair()
        cs, cc = _sock.socketpair()
        us.sendall(fake_resp)
        us.shutdown(_sock.SHUT_WR)
        _rmod.Proxy._pipe_injected(object(), cc, uc)
        cs.settimeout(2)
        got = b""
        try:
            while True:
                ch = cs.recv(65536)
                if not ch:
                    break
                got += ch
        except OSError:
            pass
        for s in (us, uc, cs, cc):
            s.close()
        return got

    _spec = _ilu.spec_from_file_location("router_mod", "/opt/data/router.py")
    _rmod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_rmod)
    out = run_pipe(
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
        b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        b"<html><head><title>t</title></head><body>hi</body></html>")
    check("B: fallback injects watchdog into text/html + reframes "
          "(chunked → Content-Length)",
          b"CB session watchdog" in out and b"<title>t</title>" in out
          and b"Content-Length:" in out
          and b"Transfer-Encoding" not in out,
          out[:160].decode("latin1", "replace"))
    fake_js = (b"HTTP/1.1 200 OK\r\nContent-Type: application/javascript\r\n"
               b"Content-Length: 4\r\n\r\nvar x")
    out2 = run_pipe(fake_js)
    check("B: non-HTML passes through un-injected, byte-identical",
          out2 == fake_js and b"CB session watchdog" not in out2,
          out2[:120].decode("latin1", "replace"))

    # Spec 39: the watchdog JS must carry the escalation and interpolate the
    # rescue envs (unit-level — the live HTTP rescue path is tested above).
    _wj = _rmod._inject_watchdog("<html><head></head><body>x</body></html>")
    check("spec39: watchdog v2 embeds /fleet/rescue escalation",
          "/fleet/rescue" in _wj and "stuck" in _wj
          and "RESCUE_AFTER" in _wj and "COOLDOWN" in _wj, "")
    check("spec39: watchdog interpolates rescue envs (placeholders gone)",
          "__RESCUE_AFTER__" not in _wj and "__RESCUE_COOLDOWN_MS__" not in _wj
          and "RESCUE_AFTER = " in _wj and "COOLDOWN = " in _wj, "")

    # Spec 40: watchdog v3 — stream-dead detection (video currentTime stall
    # / absent media) must be embedded and its env interpolated.
    check("spec40: watchdog v3 embeds stream-dead escalation",
          "streamDead" in _wj and "currentTime" in _wj
          and "player-container video" in _wj
          and "rescue(\"stream-dead\")" in _wj
          and "rescue(\"login-stuck\")" in _wj, "")
    check("spec40: watchdog interpolates stream env (placeholder gone)",
          "__STREAM_AFTER__" not in _wj
          and "var STREAM_AFTER = " in _wj, "")
    check("spec40: stream-dead window = CB_STREAM_AFTER polls",
          "var STREAM_AFTER = 3" in _wj
          or "var STREAM_AFTER = 10" in _wj, "")  # env-default run

    # Spec 41 (2026-08-22, Tigo): Exit (slot release) must hand the freed
    # slot to the QUEUE HEAD — the releaser re-queues FIFO and can never cut
    # in. Live incident: spike-user2 released, his own page reload
    # archive-woke him straight back onto the slot, and the queue (spike-user,
    # montigaud) never advanced. Now: released archives never wake.
    proc.send_signal(signal.SIGTERM)
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.communicate()
    try:
        os.unlink(ST)
    except OSError:
        pass
    slot = FakeSlot()  # fixture was stopped after the live scenario (line 882)
    slot.start()
    # Long max session: this block exercises the Exit → released path, and
    # on a slower host the 4.8 s default (0.08 min) lets the reaper expire D
    # before the Exit click lands (archive reason=expired, not released).
    # Session expiry is covered by the earlier scenarios with the short max.
    proc = start_router({"CB_HUMAN_MAX_SESSION_MIN": "5"})
    time.sleep(1.5)
    st, lb, _ = http_get("/", email="d@x.pro")
    check("spec41: D acquires the free slot (auto-create, empty queue)",
          st == 200 and "Open Browser" in lb, f"status={st}")
    st, qb, _ = http_get("/", email="e@x.pro")
    check("spec41: E queued behind D",
          st == 200 and "Your position" in qb, f"status={st}")
    # The router identifies the slot owner asynchronously (daemon thread)
    # after an auto-create assignment. On a slow host the Exit click below
    # can otherwise race the identify: the slot then believes it has no
    # owner, the /release notify never lands and D stays active forever.
    # Wait for the slot to learn its owner (the production invariant —
    # a slot can only release a session it knows it owns).
    for _ in range(40):
        if slot.user == "d@x.pro":
            break
        time.sleep(0.05)
    check("spec41: slot-1 identified D before Exit", slot.user == "d@x.pro",
          str(slot.user))
    # D clicks Exit → FakeSlot /release → router archives reason=released.
    req = urllib.request.Request(
        f"http://127.0.0.1:{FAKE_RESTART}/release", method="POST",
        data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        check("spec41: D slot /release → 200", r.status == 200, str(r.status))
    time.sleep(0.6)  # release notify lands
    f41 = fleet()
    check("spec41: D archived reason=released, slot freed",
          f41["archives"].get("d@x.pro") == "released"
          and "d@x.pro" not in f41["users"] and "1" not in f41["slots"],
          json.dumps({k: f41[k] for k in ("users", "slots", "archives")}))
    # D's own page reload → queue page (NOT landing): released never wakes
    # AND the FIFO guard blocks auto-create while E is waiting.
    st, lb, _ = http_get("/", email="d@x.pro")
    check("spec41: D re-entry → queue page (no wake, no auto-create)",
          st == 200 and "Your position" in lb
          and "Your browser session is ready" not in lb, f"status={st}")
    # The QUEUE HEAD (E) is offered the freed slot and takes it.
    took = None
    d_offer = time.time() + 12
    while time.time() < d_offer:
        st, j, _ = http_get("/queue/status", email="e@x.pro")
        j = json.loads(j)
        if j.get("status") == "offered" and j.get("open_url"):
            took = j["open_url"]
            break
        time.sleep(0.5)
    check("spec41: queue head E offered the freed slot",
          took is not None, f"took={took}")
    if took:
        http_get(took, email="e@x.pro")
    st, me, _ = http_get("/fleet/my-status", email="e@x.pro")
    me = json.loads(me)
    check("spec41: E active on the slot (queue advanced)",
          st == 200 and me.get("state") == "active", json.dumps(me))
    st, md, _ = http_get("/fleet/my-status", email="d@x.pro")
    md = json.loads(md)
    check("spec41: D still queued behind E (never cut in)",
          st == 200 and md.get("state") == "queued", json.dumps(md))

    # Spec 29 regression: IDLE archives still auto-wake (walk-away resume) —
    # only released/expired/offer_expired archives must NOT wake.
    proc.send_signal(signal.SIGTERM)
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.communicate()
    # The fake slot is a persistent process across router-restart scenarios.
    # Reset its owner/Chrome state before seeding an idle archive; otherwise
    # the readiness barrier correctly rejects the previous scenario's live
    # foreign owner, turning this isolated spec-29 test into a false failure.
    slot.user = None
    slot.chrome_running = False
    slot.stale_suspend = False
    slot.notify_on_suspend = True
    seed = {
        "users": {}, "slots": {}, "sessions": {}, "queue": [], "archives": {
            "idle-walker@x.pro": {"at": time.time() - 60, "reason": "idle"}},
        "history": {}, "queue_seq": 0, "rescue_at": {},
    }
    with open(ST, "w") as f:
        json.dump(seed, f)
    proc = start_router()
    time.sleep(1.5)
    st, lb, _ = http_get("/", email="idle-walker@x.pro")
    check("spec29 regression: idle archive still wakes (Open Browser)",
          st == 200 and "Open Browser" in lb, f"status={st}")
    proc.send_signal(signal.SIGTERM)
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.communicate()

    # ---- Spec 45: stale-suspend no-op must NOT hand over a live foreign
    # ---- session on offer-take. Sequence (mirrors the live incident):
    #   1. A active on slot-1.
    #   2. A's session clock expires → reaper suspends slot-1 → slot release.
    #      But restart-api's _suspended is STALE (chrome_running=True after a
    #      bypassed /wake) — the reaper force-releases after the grace.
    #   3. B (queue head) is offered slot-1. B opens the take URL.
    #   4. Router _slot_clean must REFUSE (slot /health reports not
    #      suspended) → B stays queued.
    #   5. Slot genuinely suspends (chrome stopped) → B takes → active.
    # New restart scenario: explicitly reset the persistent fake slot to the
    # clean stopped state expected by the seeded empty router state.
    slot.user = None
    slot.chrome_running = False
    slot.stale_suspend = False
    slot.notify_on_suspend = True
    slot.pending_archive_owner = None
    seed = {
        "users": {}, "slots": {}, "sessions": {}, "queue": [], "archives": {},
        "history": {}, "queue_seq": 0, "rescue_at": {},
    }
    with open(ST, "w") as f:
        json.dump(seed, f)
    proc = start_router()
    time.sleep(1.5)
    # 1: A active
    st, lb, _ = http_get("/", email="a@x.pro")
    check("spec45: A assigned slot-1 (pre-cond)",
          st == 200 and "Your browser session is ready" in lb, f"st={st}")
    slot.user = "a@x.pro"
    # 2: A expires (5s max session) → reaper suspends; simulate the STALE
    # suspend: reaper's POST /suspend hits the fake slot, but chrome_running
    # stays True (mirrors restart-api's _suspended no-op), so the release
    # callback never fires and the reaper force-releases A. The /health
    # endpoint reports suspended=false → the take MUST be refused.
    slot.notify_on_suspend = False  # stale suspend → no release callback
    slot.stale_suspend = True  # suspend no-op → chrome stays live
    st, j, _ = http_get("/queue/status", email="b@x.pro")
    j = json.loads(j)
    check("spec45: B queued behind A", j.get("status") in ("waiting", "offered"),
          json.dumps(j))
    # 3: wait for A's force-release (expires ~4.8s + self-heal grace ≥10s).
    # With stale_suspend the slot stays dirty (chrome live) and no release
    # callback fires, so the reaper force-releases A after the grace.
    fr = False
    deadline = time.time() + 25
    while time.time() < deadline:
        j = fleet()
        if j.get("users", {}).get("a@x.pro") is None and \
                j.get("archives", {}).get("a@x.pro") == "expired":
            fr = True
            break
        time.sleep(0.5)
    check("spec46: A force-released (stale latch → no release callback)",
          fr, f"fr={fr} users={j.get('users')} archives={j.get('archives')}")
    # 4: the freed slot is DIRTY (chrome live) → the reaper's self-heal
    # sweep re-suspends it and MUST NOT offer it. Assert B stays "waiting"
    # over a window, and that the self-heal actually fired a /suspend.
    susp_before = slot.suspends
    dirty_not_offered = True
    deadline = time.time() + 6
    while time.time() < deadline:
        st, j, _ = http_get("/queue/status", email="b@x.pro")
        j = json.loads(j)
        if j.get("status") == "offered":
            dirty_not_offered = False
            break
        time.sleep(0.5)
    check("spec46: dirty slot NOT offered (self-heal re-suspends)",
          dirty_not_offered and slot.suspends > susp_before,
          f"offered={not dirty_not_offered} suspends={slot.suspends} "
          f"status={j.get('status')}")
    # 5: slot genuinely suspends (spec-45 restart-api force-teardown now
    # works) → self-heal converges → reaper offers B.
    slot.chrome_running = False
    slot.stale_suspend = False
    slot.notify_on_suspend = True
    took = None
    deadline = time.time() + 20
    while time.time() < deadline:
        st, j, _ = http_get("/queue/status", email="b@x.pro")
        j = json.loads(j)
        if j.get("status") == "offered" and j.get("open_url"):
            took = j["open_url"]
            break
        time.sleep(0.5)
    check("spec45: B offered once slot genuinely suspended",
          took is not None, f"took={took}")
    if took:
        # 6: take-time isolation backstop — make the slot report dirty at
        # take time (re-arm the stale latch); _slot_clean must refuse.
        slot.stale_suspend = True
        slot.chrome_running = True
        st, lb, _ = http_get(took, email="b@x.pro")
        check("spec45: take REFUSED (queue page, not landing)",
              st == 200 and "Your position" in lb,
              f"st={st} body={lb[:80]}")
        st, mb, _ = http_get("/fleet/my-status", email="b@x.pro")
        mb = json.loads(mb)
        check("spec45: B still queued after refused take (isolation)",
              st == 200 and mb.get("state") == "queued", json.dumps(mb))
        # 7: slot genuinely suspends again → the SAME offer is still valid
        # (grace not elapsed) → B takes → active, and the take wakes the
        # slot (spec 46).
        slot.stale_suspend = False
        slot.chrome_running = False
        http_get(took, email="b@x.pro")
        time.sleep(0.5)
        st, mb, _ = http_get("/fleet/my-status", email="b@x.pro")
        mb = json.loads(mb)
        check("spec45: B active once slot actually suspended",
              st == 200 and mb.get("state") == "active", json.dumps(mb))
        # Spec 46: the offer-take MUST have woken the slot (Chrome started
        # for the new owner). spec-42 removed the offer-time pre-wake and
        # never made the take wake — a latent bug that handed every
        # offer-take a suspended slot (neko UI, no Chrome). _slot_clean
        # proved the slot clean; the take now wakes it.
        check("spec46: take woke the slot (chrome running)",
              slot.wakes >= 1 and slot.chrome_running is True,
              f"wakes={slot.wakes} chrome_running={slot.chrome_running}")

    # ------------------------------------------------------------------
    # Spec 77 (2026-08-28): ghost-offer backoff + owner-bound boot hint.
    # Run on a FRESH router subprocess so the prior suite's queue / state
    # don't leak into the assertions. CB_OFFER_GRACE_S=2 + CB_OFFER_BACKOFF_*
    # thresholds keep this in <30 s.
    # ------------------------------------------------------------------
    try:
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.communicate()
    try:
        slot.stop()
    except Exception:
        pass
    time.sleep(0.3)
    try:
        os.unlink(ST)
    except OSError:
        pass
    slot77 = FakeSlot()
    slot77.start()
    proc77 = start_router(extra_env={
        "CB_OFFER_GRACE_S": "2",
        "CB_REAPER_INTERVAL_S": "1",
        "CB_OFFER_BACKOFF_THRESHOLD": "3",
        "CB_OFFER_BACKOFF_WINDOW_S": "600",
        "CB_OFFER_BACKOFF_COOLDOWN_S": "900",
    })
    time.sleep(1.5)

    # 77.a — third offer-expiry for (montigaud, slot-1) flips the entry to
    # status=backed_off (off the offer scan). Drive the livelock: A active
    # on slot-1, montigaud queued, then cycle A release → slot frees →
    # montigaud offered → grace expires → waiting → A re-entries (auto
    # -create on slot-1, spec 41) → cycle repeats. After the third expiry
    # the entry must transition to backed_off.
    http_get("/", email="a77@x.pro")  # A active on slot-1
    time.sleep(0.3)
    http_get("/", email="montigaud@x.pro")  # queued (slot occupied)
    time.sleep(0.3)
    backed_seen = False
    release_cycles = 0
    deadline77 = time.time() + 45
    while time.time() < deadline77:
        f77 = fleet()
        m77 = next((e for e in f77.get("queue", [])
                    if e.get("email") == "montigaud@x.pro"), None)
        if m77 and m77.get("status") == "backed_off":
            backed_seen = True
            break
        a77_active = f77.get("users", {}).get("a77@x.pro")
        if a77_active:
            # A active: release A → slot frees → reaper offers slot-1
            # to montigaud → grace 2 s → expiry cycle.
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{FAKE_RESTART}/release", method="POST",
                    data=b"{}", headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=5).read()
            except Exception:
                pass
            release_cycles += 1
        else:
            # Slot is free — re-arm A so the slot is occupied and
            # montigaud cycles back into the queue (spec 41: re-queue
            # FIFO, slot offered to queue head).
            http_get("/", email="a77@x.pro")
            time.sleep(0.3)
        time.sleep(2.5)
    check("spec77: ghost-offer backoff — third expiry flips to backed_off",
          backed_seen,
          f"backed_seen={backed_seen} release_cycles={release_cycles} queue="
          f"{json.dumps([(e['email'], e.get('status')) for e in fleet().get('queue', [])])}")
    # 77.a-2 — backed_off entries are NOT re-offered while cooldown holds.
    if backed_seen:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{FAKE_RESTART}/release", method="POST",
                data=b"{}", headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
        time.sleep(5.0)
        m77 = next((e for e in fleet().get("queue", [])
                    if e.get("email") == "montigaud@x.pro"), None)
        check("spec77: backed_off entry NOT re-offered while cooldown holds",
              m77 is not None and m77.get("status") == "backed_off",
              json.dumps(m77))

    # 77.b — restart-api boot hint: SLOT_USER_FILE empty + archive
    # present ⇒ _boot_archive_owner returns the most-recent real archive.
    # SESSIONS_DIR layout mirrors production (/data/sessions/<email>/):
    # entries are USER DIRECTORIES, each with profile/Default + Preferences.
    probe = "/tmp/spec77-boot-probe"
    if os.path.isdir(probe):
        shutil.rmtree(probe)
    os.makedirs(f"{probe}/archives/spike-probe@x.pro/profile/Default",
                exist_ok=True)
    os.makedirs(f"{probe}/archives/empty@x.pro", exist_ok=True)
    open(f"{probe}/archives/spike-probe@x.pro/profile/Preferences",
         "w").write("{}")
    os.utime(f"{probe}/archives/spike-probe@x.pro/profile/Default",
             (time.time(), time.time()))
    import importlib.util as _ilu
    sys.modules.pop("restart_api_probe", None)
    spec_mod = _ilu.spec_from_file_location(
        "restart_api_probe",
        "/opt/data/restart-api.py")
    rap = _ilu.module_from_spec(spec_mod)
    try:
        spec_mod.loader.exec_module(rap)
        # Override production paths only after import so this probe cannot
        # touch /data/sessions or the real slot marker.
        rap.SESSIONS_DIR = f"{probe}/archives"
        rap.SLOT_USER_FILE = f"{probe}/.slot-user.json"
    except Exception as e:
        check("spec77: restart-api imports cleanly for probe", False,
              f"import error: {e}")
    else:
        hint = rap._boot_archive_owner()
        check("spec77: boot hint = spike-probe@x.pro when archive present",
              hint == "spike-probe@x.pro", f"hint={hint!r}")
        rap._slot_user = None
        open(rap.SLOT_USER_FILE, "w").write(json.dumps(
            {"user": "spike-probe@x.pro", "slot": 1}))
        hint2 = rap._boot_archive_owner()
        check("spec77: boot hint null when slot already bound",
              hint2 is None, f"hint={hint2!r}")
        rap._slot_user = None
        os.remove(rap.SLOT_USER_FILE)
        # No real archive left → hint null (the empty@x.pro dir has no
        # profile/Default, so it must not qualify).
        shutil.rmtree(f"{probe}/archives/spike-probe@x.pro")
        hint3 = rap._boot_archive_owner()
        check("spec77: boot hint null when no real archive",
              hint3 is None, f"hint={hint3!r}")

    # 77.c — router boot-hint sweep end-to-end. A slot reporting
    # pending_archive_owner must be woken for that owner with the
    # assignment RECORDED in router state (users/slots/sessions), and the
    # hint is one-shot: once the slot is bound, no re-wake. Live bug
    # 2026-08-28: the sweep woke the same owner into TWO slots and never
    # recorded the assignment (users stayed {} while the slot served the
    # owner).
    try:
        proc77.send_signal(signal.SIGTERM)
        proc77.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc77.kill(); proc77.communicate()
    try:
        slot77.stop()
    except Exception:
        pass
    time.sleep(0.3)
    try:
        os.unlink(ST)
    except OSError:
        pass
    slot77c = FakeSlot()
    slot77c.pending_archive_owner = "spike-hint@x.pro"
    slot77c.start()
    proc77c = start_router(extra_env={
        "CB_OFFER_GRACE_S": "2",
        "CB_REAPER_INTERVAL_S": "1",
        "CB_OFFER_BACKOFF_THRESHOLD": "3",
        "CB_OFFER_BACKOFF_WINDOW_S": "600",
        "CB_OFFER_BACKOFF_COOLDOWN_S": "900",
        "IDENTIFY_SWEEP_INTERVAL": "2",  # fast boot-hint sweep for the test
    })
    time.sleep(1.5)
    recovered = False
    deadline = time.time() + 15
    while time.time() < deadline:
        f = fleet()
        if f.get("users", {}).get("spike-hint@x.pro") == 1:
            recovered = True
            break
        time.sleep(0.5)
    check("spec77: boot hint wakes the owner AND records the assignment",
          recovered and slot77c.wakes >= 1
          and slot77c.user == "spike-hint@x.pro",
          f"recovered={recovered} wakes={slot77c.wakes} "
          f"user={slot77c.user} users={fleet().get('users')}")
    w1 = slot77c.wakes
    time.sleep(5)  # several sweep ticks while the slot is busy
    check("spec77: no re-wake while the owner is active on the slot",
          slot77c.wakes == w1 and slot77c.pending_archive_owner is None,
          f"wakes={slot77c.wakes} (was {w1})")
    # Release the owner; the hint was consumed at wake (one-shot per boot),
    # so the slot must NOT be re-woken by the sweep.
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{FAKE_RESTART}/release", method="POST",
            data=b"{}", headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass
    time.sleep(5)  # sweep ticks after the release
    check("spec77: hint is one-shot — no re-wake after release",
          slot77c.wakes == w1 and slot77c.pending_archive_owner is None
          and fleet().get("users", {}).get("spike-hint@x.pro") is None,
          f"wakes={slot77c.wakes} (was {w1}) "
          f"users={fleet().get('users')}")
    # Edge (live 2026-08-28): a slot whose hint was NEVER consumed (owner
    # was live elsewhere when probed) must not re-wake that owner later —
    # e.g. after the owner's session on another slot ends, the armed hint
    # would otherwise auto-re-open their session. Re-arm the hint on the
    # (now free) slot and assert the router's one-shot memory holds.
    slot77c.pending_archive_owner = "spike-hint@x.pro"
    time.sleep(5)  # several sweep ticks with the re-armed hint
    check("spec77: consumed hint never re-dispatched (one-shot per owner)",
          slot77c.wakes == w1 and slot77c.user != "spike-hint@x.pro"
          and fleet().get("users", {}).get("spike-hint@x.pro") is None,
          f"wakes={slot77c.wakes} (was {w1}) "
          f"user={slot77c.user} users={fleet().get('users')}")

    for p in (proc77c,):
        try:
            p.send_signal(signal.SIGTERM)
            p.communicate(timeout=5)
        except Exception:
            try:
                p.kill(); p.communicate()
            except Exception:
                pass
    try:
        slot77c.stop()
    except Exception:
        pass

    print(f"\nRESULT: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
