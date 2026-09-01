#!/usr/bin/env python3
"""Regression checks for the CloudBrowser queue Open Browser action.

A user may have an old ``backed_off`` queue record and a newer ``waiting`` or
``offered`` record after re-enqueue.  The status endpoint must select the
current record; otherwise the queue list shows the user while the Open Browser
button remains hidden.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE

spec = importlib.util.spec_from_file_location("router_under_test", SCRIPTS / "router.py")
router = importlib.util.module_from_spec(spec)
assert spec.loader
os.environ["CB_AGENT_TOKEN"] = ""
spec.loader.exec_module(router)


def check(name: str, condition: bool, detail: str = "") -> None:
    print(("PASS " if condition else "FAIL ") + name + (f"  {detail}" if detail else ""))
    if not condition:
        raise SystemExit(1)


class Stub:
    def _resolve(self):
        return None, False

    def _enqueue_human(self, email):
        raise AssertionError(f"unexpected enqueue for {email}")

    def _open_url(self, email, goto=None):
        return f"/?pwd=neko&usr={email.replace('@', '%40')}"


def state(entries):
    return {
        "users": {},
        "slots": {},
        "sessions": {},
        "archives": {},
        "queue": entries,
        "history": {"human": []},
        "queue_seq": 20,
        "rescue_at": {},
    }


email = "spike-user@aikumi.pro"
now = time.time()
old_backoff = {
    "id": "q-old",
    "type": "human",
    "email": email,
    "status": "backed_off",
    "enqueued_at": now - 120,
    "offer_expires_at": None,
    "backed_off_until": now + 600,
}

waiting = {
    "id": "q-current",
    "type": "human",
    "email": email,
    "status": "waiting",
    "enqueued_at": now,
    "offer_expires_at": None,
}
original = router._state
router._state = state([old_backoff, waiting])
try:
    out = router.Proxy._human_status(Stub(), email)
finally:
    router._state = original
check(
    "stale backed-off entry no longer hides current waiting entry",
    out.get("status") == "waiting" and out.get("position") == 1,
    json.dumps(out),
)
check(
    "waiting entry has no Open Browser URL",
    "open_url" not in out,
    json.dumps(out),
)

offered = {
    "id": "q-offer",
    "type": "human",
    "email": email,
    "status": "offered",
    "enqueued_at": now,
    "offer_expires_at": now + 45,
    "slot": 1,
}
router._state = state([old_backoff, offered])
try:
    out = router.Proxy._human_status(Stub(), email)
finally:
    router._state = original
check(
    "stale backed-off entry no longer hides current offer",
    out.get("status") == "offered" and out.get("position") == 1,
    json.dumps(out),
)
check(
    "current offer exposes Open Browser URL and countdown",
    bool(out.get("open_url")) and out.get("offer_ttl_s", 0) > 0,
    json.dumps(out),
)

print("RESULT: 4 passed, 0 failed")
