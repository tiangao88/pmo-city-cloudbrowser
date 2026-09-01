#!/usr/bin/env python3
"""Regression tests for the live CloudBrowser session timer gap (spec 65
countdown missing on the kiosk top bar) and the MFA chat-ask cancellation
loop (broker cancelling every challenge because the identity sweep rewrites
the slot marker every 30 s).

Root causes (live-verified 2026-08-27 on cb-fleet-v2, slot-1):
  A. router `_human_status()` early-returns `{"status":"active",
     "open_url": ...}` for an ACTIVE user who has NO queue entry (the
     common auto-create / archive-wake path), so the title-proxy countdown
     poller never sees `session_ttl_s` and keeps the timer hidden.
  B. router `_sweep_loop()` re-POSTs `/identify` every SWEEP_INTERVAL for
     every active user; restart-api `set_slot_user()` rewrites the marker
     with a NEW `ts`, so the broker's `marker_snapshot()` generation
     changes every sweep → `handle_mfa` revalidate() fails → the broker
     cancels a fresh OTP challenge ~6 s after arming it, forever.

This file asserts the two fixed behaviors (RED on the current deployed
source, GREEN on the patched source). It imports the REAL router.py and
restart-api.py from the repo and does not start any server.

Usage:
  python3 test-spec65-ttl-and-sweep.py  [repo scripts dir]
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = Path(sys.argv[1] if len(sys.argv) > 1 else HERE)

failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if detail else ""))
    if not ok:
        failures.append(name)


# --- Case A: active user WITHOUT a queue entry gets session_ttl_s ---------
spec = importlib.util.spec_from_file_location("router_under_test",
                                              SCRIPTS / "router.py")
rt = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(rt)

state = {
    "users": {"spike-user@aikumi.pro": 1},
    "slots": {"1": "spike-user@aikumi.pro"},
    "sessions": {"spike-user@aikumi.pro": {"slot": 1,
                                           "started_at": time.time() - 60,
                                           "tier": "human"}},
    "archives": {},
    "queue": [],
    "history": {},
    "queue_seq": 0,
    "rescue_at": {},
}


class Stub:
    """Proxy-like object exposing only what _human_status needs."""

    def __init__(self, st, email):
        self._state = st
        self._email = email

    def _resolve(self):
        email = self._email
        if email in self._state["users"]:
            return self._state["users"][email], False
        return None, False

    def _open_url(self, email, goto=None):
        return f"/?pwd=neko&usr={email.replace('@', '%40')}"

    def _enqueue_human(self, email):
        raise AssertionError("_enqueue_human must not run for an active user")

    def _ensure_slot_ready(self, k, email):
        return True


orig_state = rt._state
rt._state = state
try:
    out = rt.Proxy._human_status(Stub(state, "spike-user@aikumi.pro"),
                                 "spike-user@aikumi.pro")
finally:
    rt._state = orig_state

check("active-no-queue-entry: status active",
      out.get("status") == "active", json.dumps(out))
check("active-no-queue-entry: open_url present",
      bool(out.get("open_url")), json.dumps(out))
check("active-no-queue-entry: session_ttl_s present (>0)",
      isinstance(out.get("session_ttl_s"), int) and out["session_ttl_s"] > 0,
      json.dumps(out))

# A waiting user must NOT receive the TTL (no running session clock).
state_q = {
    "users": {"other@x.pro": 2},
    "slots": {"2": "other@x.pro"},
    "sessions": {"other@x.pro": {"slot": 2,
                                 "started_at": time.time() - 60,
                                 "tier": "human"}},
    "archives": {},
    "queue": [{"id": "q-9", "type": "human", "email": "waiter@x.pro",
               "status": "waiting", "enqueued_at": time.time(),
               "offer_expires_at": None}],
    "history": {},
    "queue_seq": 10,
    "rescue_at": {},
}
rt._state = state_q
try:
    out2 = rt.Proxy._human_status(Stub(state_q, "waiter@x.pro"), "waiter@x.pro")
finally:
    rt._state = orig_state
check("waiting user: NOT active, no session_ttl_s",
      out2.get("status") == "waiting" and out2.get("session_ttl_s") is None,
      json.dumps(out2))


# --- Case B: identify sweep must NOT churn the marker generation ----------
# Import the REAL restart-api with a temp DOWNLOADS_DIR so the marker
# lands in a scratch dir.
tmpdir = Path(tempfile.mkdtemp(prefix="cb-marker-"))
os.environ["DOWNLOADS_DIR"] = str(tmpdir)
rspec = importlib.util.spec_from_file_location("restart_api_under_test",
                                               SCRIPTS / "restart-api.py")
rapi = importlib.util.module_from_spec(rspec)
assert rspec.loader
rspec.loader.exec_module(rapi)
marker = tmpdir / ".slot-user.json"

# Seed a STALE marker (older ts than now): a same-owner re-assert (the
# sweep) must NOT rewrite it — deterministic even with 1s ts granularity
# (old code rewrites ts to now → RED; fixed code no-ops → ts stays 1000).
marker.write_text(json.dumps({"user": "spike-user@aikumi.pro",
                              "slot": 1, "ts": 1000}))
rapi.set_slot_user("spike-user@aikumi.pro", 1)  # sweep re-assert (same)
after_assert = json.loads(marker.read_text())
check("identify re-assert: marker ts NOT rewritten (stays 1000)",
      after_assert.get("ts") == 1000, json.dumps(after_assert))
check("identify re-assert: marker user/slot unchanged",
      after_assert.get("user") == "spike-user@aikumi.pro"
      and after_assert.get("slot") == 1, json.dumps(after_assert))

# A different owner must still rotate the marker (identity change).
rapi.set_slot_user("other@aikumi.pro", 1)
third = json.loads(marker.read_text())
check("identify push: owner change still rotates ts",
      third.get("user") == "other@aikumi.pro"
      and third.get("ts") != 1000, json.dumps(third))

# Broker generation snapshot must stay equal across the sweep.
def marker_snapshot_sim(path=marker):
    try:
        m = json.loads(path.read_text())
        return (m["user"].lower(), int(m["slot"]), float(m["ts"]))
    except Exception:
        return None

g1 = marker_snapshot_sim()
rapi.set_slot_user("other@aikumi.pro", 1)  # another same-owner re-assert
g2 = marker_snapshot_sim()
check("broker generation stable across same-owner re-assert sweep",
      g1 == g2, f"g1={g1} g2={g2}")

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL PASS")
