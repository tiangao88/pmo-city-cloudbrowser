#!/usr/bin/env python3
"""W3-1A queue/identity reconciliation regression tests.

This is deliberately a source-level behavioral test: it imports the real
router module and exercises the same state transitions used by the HTTP
handler, without contacting the live fleet or mutating a user session.

W3-1A contract:
  * an active identity with no queue row is reported active with a TTL;
  * a waiting identity receives a stable 1-based position;
  * a backed-off identity is explicitly represented, never rendered as an
    unexplained queue position;
  * the queue payload distinguishes the caller from the other active user;
  * a queued page's source contains a polling path that turns an active result
    into an Open Browser link rather than a permanent '?'.

Run:
  python3 test-w3-1a-queue-reconciliation.py [router.py]
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTER = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "router.py"

spec = importlib.util.spec_from_file_location("router_w3_1a_under_test", ROUTER)
if spec is None or spec.loader is None:
    raise SystemExit(f"cannot load {ROUTER}")
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        failures.append(name)


class Stub:
    """Minimal Proxy dependency surface for _human_status."""

    def __init__(self, state: dict, email: str):
        self._state = state
        self._email_value = email

    def _email(self):
        return self._email_value

    def _resolve(self):
        if self._email_value in self._state["users"]:
            return self._state["users"][self._email_value], False
        return None, False

    def _open_url(self, email: str, goto=None):
        return f"/?pwd=REDACTED&usr={email.replace('@', '%40')}"

    def _ensure_slot_ready(self, k, email):
        return True

    def _rollback_unready_assignment(self, email, k):
        return None

    def _waiting_status(self, email):
        return {"status": "waiting", "position": 1,
                "waiting": [{"email": email, "pos": 1}],
                "active_humans": [], "agent_count": 0}

    def _enqueue_human(self, email: str):
        now = time.time()
        self._state["queue"].append({
            "id": "auto-1", "type": "human", "email": email,
            "priority": 0, "enqueued_at": now, "status": "waiting",
            "offer_expires_at": None,
        })
        return "auto-1"


def base_state() -> dict:
    return {
        "users": {"active@x.pro": 1},
        "slots": {"1": "active@x.pro"},
        "sessions": {"active@x.pro": {
            "slot": 1, "started_at": time.time() - 30, "tier": "human",
        }},
        "archives": {},
        "queue": [],
        "history": {},
        "queue_seq": 0,
        "rescue_at": {},
    }


# 1. Active caller without a queue row: no '?', has a running-session TTL.
state = base_state()
orig = rt._state
rt._state = state
try:
    active = rt.Proxy._human_status(Stub(state, "active@x.pro"), "active@x.pro")
finally:
    rt._state = orig
check("active/no-queue reports active", active.get("status") == "active", active)
check("active/no-queue has open_url", bool(active.get("open_url")), active)
check(
    "active/no-queue has positive session TTL",
    isinstance(active.get("session_ttl_s"), int) and active["session_ttl_s"] > 0,
    active,
)
check("active/no-queue uses session state, not queue position", active.get("status") == "active" and "position" not in active, active)

# 2. Waiting caller: stable position and no running-session TTL.
state = base_state()
state["queue"] = [{
    "id": "q-wait", "type": "human", "email": "wait@x.pro",
    "priority": 0, "enqueued_at": time.time(), "status": "waiting",
    "offer_expires_at": None,
}]
orig = rt._state
rt._state = state
try:
    waiting = rt.Proxy._human_status(Stub(state, "wait@x.pro"), "wait@x.pro")
finally:
    rt._state = orig
check("waiting caller reports waiting", waiting.get("status") == "waiting", waiting)
check("waiting caller gets position 1", waiting.get("position") == 1, waiting)
check("waiting caller has no session TTL", waiting.get("session_ttl_s") is None, waiting)
check(
    "waiting list includes caller with position",
    {x.get("email"): x.get("pos") for x in waiting.get("waiting", [])}.get("wait@x.pro") == 1,
    waiting,
)

# 3. Backed-off caller: status is explicit and position is intentionally absent.
state = base_state()
state["queue"] = [{
    "id": "q-backoff", "type": "human", "email": "backoff@x.pro",
    "priority": 0, "enqueued_at": time.time(), "status": "backed_off",
    "offer_expires_at": None, "backed_off_until": time.time() + 120,
}]
orig = rt._state
rt._state = state
try:
    backed = rt.Proxy._human_status(Stub(state, "backoff@x.pro"), "backoff@x.pro")
finally:
    rt._state = orig
check("backed-off caller reports explicit backed_off", backed.get("status") == "backed_off", backed)
check("backed-off caller has backoff TTL", backed.get("backoff_ttl_s", 0) > 0, backed)
check("backed-off caller has no misleading position", backed.get("position") is None, backed)

# 4. Two identities: each response is keyed to its own identity.
state = base_state()
state["users"]["other@x.pro"] = 2
state["slots"]["2"] = "other@x.pro"
state["sessions"]["other@x.pro"] = {
    "slot": 2, "started_at": time.time() - 20, "tier": "human",
}
state["queue"] = [{
    "id": "q-wait", "type": "human", "email": "wait@x.pro",
    "priority": 0, "enqueued_at": time.time(), "status": "waiting",
    "offer_expires_at": None,
}]
orig = rt._state
rt._state = state
try:
    first = rt.Proxy._human_status(Stub(state, "active@x.pro"), "active@x.pro")
    second = rt.Proxy._human_status(Stub(state, "wait@x.pro"), "wait@x.pro")
finally:
    rt._state = orig
check(
    "active identity receives an active response while another user is queued",
    first.get("status") == "active" and "position" not in first
    and "active@x.pro" not in first.get("active_humans", []),
    first,
)
check(
    "waiting identity sees both active identities",
    set(second.get("active_humans", [])) == {"active@x.pro", "other@x.pro"},
    second,
)

# 5. The queue document must keep polling and expose the active Open Browser path.
source = (ROUTER.parent / "router.py").read_text(encoding="utf-8")
queue_source = source[source.index("def _queue_page"):source.index("def _watchdog_html") if "def _watchdog_html" in source else source.index("_WATCHDOG =")]
check("queue page polls queue/status", "fetch('/queue/status'" in queue_source, "queue page source")
check("queue page has Open Browser target", "b.href = j.open_url" in queue_source, "queue page source")
check("queue page has explicit unknown fallback", "j.position ?? '?'" in queue_source, "queue page source")

# 6. Active-session redirects must be explicitly framed. An HTTP/1.1 client
# otherwise has no reliable end-of-response signal and can keep showing a
# loading/stop indicator after the target page rendered.
check("active reload redirect has zero-length framing",
      'self.send_header("Content-Length", "0")' in source,
      "router source")
check("active reload redirect closes the connection",
      'self.send_header("Connection", "close")' in source,
      "router source")

# 7. Router request logging must not retain Neko's password-bearing query.
check("router logs path without query string",
      "urlsplit(self.path).path" in source
      and 'print(f"[router] {self.command} {path}' in source,
      "router source")

print(json.dumps({"passed": 0 if failures else 1, "failures": failures}, sort_keys=True))
raise SystemExit(1 if failures else 0)
