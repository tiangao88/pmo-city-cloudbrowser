#!/usr/bin/env python3
"""Render the queue page in an OFFERED state (headless Chromium) and prove
the grace countdown renders + ticks down (Tigo 2026-08-22: '?' → countdown).

Boots the router via router-bootstrap.py with a seeded offered entry,
then drives it with Playwright carrying Remote-Email: offer@x.pro.
"""
import json, os, subprocess, sys, time

ST = "/tmp/router31-test-state.json"
NOW = time.time()
seed = {
    "users": {},
    "slots": {},
    "queue": [{"id": "q-1", "email": "offer@x.pro", "type": "human",
               "status": "offered", "enqueued_at": NOW - 10,
               "offer_expires_at": NOW + 65, "slot": 1}],
    "sessions": {},
    "archives": {},
    "queue_seq": 2,
}
json.dump(seed, open(ST, "w"))

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
    # wait for router (/health: 200 for any caller — the root 401s
    # anonymous requests and would burn the grace window in retries)
    for _ in range(40):
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_extra_http_headers({"Remote-Email": "offer@x.pro"})
        pg.goto("http://127.0.0.1:18082/", wait_until="networkidle")
        pg.wait_for_timeout(1500)
        lbl = pg.eval_on_selector(".lbl", "el => el.textContent")
        pos1 = pg.eval_on_selector("#pos", "el => el.textContent")
        eta = pg.eval_on_selector("#eta", "el => el.textContent")
        btn = pg.eval_on_selector("#btn", "el => el.className")
        pg.wait_for_timeout(2500)
        pos2 = pg.eval_on_selector("#pos", "el => el.textContent")
        pg.screenshot(path="/tmp/offer-countdown.png")
        b.close()
        print("LABEL :", lbl)
        print("POS-1 :", pos1)
        print("POS-2 :", pos2)
        print("ETA   :", repr(eta))
        print("BTN   :", btn)
        ok = ("Offer expires in" in lbl and pos1 != "?" and pos2 != "?"
              and "hidden" not in btn)
        # mm:ss strictly decreasing
        def secs(v):
            m, s = v.split(":"); return int(m) * 60 + int(s)
        ok = ok and secs(pos2) < secs(pos1)
        print("RESULT:", "PASS" if ok else "FAIL")
        sys.exit(0 if ok else 1)
finally:
    proc.terminate()
    proxy.terminate()
    try:
        proc.wait(timeout=5)
        proxy.wait(timeout=5)
    except Exception:
        proc.kill()
        proxy.kill()
