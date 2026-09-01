#!/usr/bin/env python3
"""Regression test (Tigo 2026-08-22): when an OFFER EXPIRES, the queue page
must re-render the user at their NEW queue position instead of freezing on
'Offer expires in 0:00' with a dead Open Browser button.

Root cause fixed: the queue-page poll used clearInterval(timer) the moment
the button was revealed (offered/active), so a lapsed offer never
re-rendered. The poll now keeps running; the zombie-button guard hides the
dead button and restores 'Your position' + position + list.

Setup mirrors the live incident (montigaud offered, two rivals waiting):
  q-1 offer@x.pro OFFERED (slot 1, 8 s grace left, enqueued NOW-20)
  q-2 other@x.pro WAITING (enqueued NOW-30  -> OLDER: after the lapse the
      re-offer goes to him, so offer@x.pro stays WAITING at the back)
A minimal FakeSlot answers /wake 200 on 127.0.0.1:9230 so offers survive
(production behavior: slots are real). Chromium is launched FIRST so the
grace window isn't consumed by browser startup.

Flow: page loads while offered (button visible) -> grace lapses -> reaper
demotes offer@x.pro to the back (offer_expired archive), re-offers to
other@x.pro -> the live poll re-renders: 'Your position', pos 2, button
hidden, list '1. other@x.pro / 2. offer@x.pro'.
"""
import http.server, json, os, subprocess, sys, threading, time

from playwright.sync_api import sync_playwright

ST = "/tmp/router31-test-state.json"
NOW = time.time()
seed = {
    "users": {},
    "slots": {},
    "queue": [
        {"id": "q-1", "email": "offer@x.pro", "type": "human",
         "status": "offered", "enqueued_at": NOW - 20,
         "offer_expires_at": NOW + 8, "slot": 1},
        {"id": "q-2", "email": "other@x.pro", "type": "human",
         "status": "waiting", "enqueued_at": NOW - 30,
         "offer_expires_at": None},
    ],
    "sessions": {},
    "archives": {},
    "queue_seq": 3,
}
json.dump(seed, open(ST, "w"))


class FakeSlot(http.server.BaseHTTPRequestHandler):
    def _ok(self):
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._ok()

    def do_GET(self):
        self._ok()

    def log_message(self, *a):
        pass


slot = http.server.ThreadingHTTPServer(("127.0.0.1", 9230), FakeSlot)
threading.Thread(target=slot.serve_forever, daemon=True).start()

env = dict(os.environ)
env.update({
    "ROUTER_PORT": "18081", "ROUTER_STATE": ST,
    "CB_HUMAN_SLOTS": "1", "CB_AGENT_SLOTS": "0",
    "CB_HUMAN_MAX_SESSION_MIN": "0.08", "CB_AGENT_MAX_SESSION_MIN": "240",
    "CB_QUEUE_POLL_INTERVAL_S": "1", "CB_REAPER_INTERVAL_S": "1",
    "CB_OFFER_GRACE_S": "60", "CB_QUEUE_SHOW_EMAILS": "true",
    "CB_ADMIN_EMAILS": "", "CB_AGENT_TOKEN": "", "NEKO_PASSWORD": "neko",
})
proc = subprocess.Popen([sys.executable, "/opt/data/router-bootstrap.py"],
                        env=env, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
proxy = subprocess.Popen([sys.executable, "/opt/data/host-proxy.py", "18082"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_extra_http_headers({"Remote-Email": "offer@x.pro"})
        pg.goto("http://127.0.0.1:18082/", wait_until="networkidle")
        # Phase 1: the offered render must appear (bounded poll — the 8 s
        # grace covers boot + goto latency).
        lbl1 = btn1 = None
        for _ in range(14):
            try:
                lbl1 = pg.eval_on_selector(".lbl", "el => el.textContent")
                btn1 = pg.eval_on_selector("#btn", "el => el.className")
            except Exception:
                pass
            if lbl1 and "Offer expires in" in lbl1 and "hidden" not in btn1:
                break
            pg.wait_for_timeout(500)
        # Phase 2: grace lapses -> reaper demotes offer@x.pro to the back,
        # re-offers other@x.pro; the live poll must re-render the viewer
        # as waiting at position 2 (the FIX: no more frozen 0:00).
        lbl2 = pos2 = btn2 = list2 = None
        for _ in range(40):
            try:
                lbl2 = pg.eval_on_selector(".lbl", "el => el.textContent")
                pos2 = pg.eval_on_selector("#pos", "el => el.textContent")
                btn2 = pg.eval_on_selector("#btn", "el => el.className")
                list2 = pg.eval_on_selector("#waiting", "el => el.textContent")
            except Exception:
                pass
            if lbl2 == "Your position" and pos2.strip() == "2" \
                    and "hidden" in btn2:
                break
            pg.wait_for_timeout(500)
        pg.screenshot(path="/tmp/lapse-render.png")
        b.close()
        print("LBL-1 :", lbl1)
        print("BTN-1 :", btn1)
        print("LBL-2 :", lbl2)
        print("POS-2 :", pos2)
        print("BTN-2 :", btn2)
        print("LIST-2:", list2)
        ok = ("Offer expires in" in lbl1 and "hidden" not in btn1
              and lbl2 == "Your position" and pos2.strip() == "2"
              and "hidden" in btn2
              and "1.other@x.pro" in list2 and "2.offer@x.pro" in list2)
        print("RESULT:", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
finally:
    proc.terminate()
    proxy.terminate()
    slot.shutdown()
    try:
        proc.wait(timeout=5)
        proxy.wait(timeout=5)
    except Exception:
        proc.kill()
        proxy.kill()
