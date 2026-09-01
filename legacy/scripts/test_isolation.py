#!/usr/bin/env python3
"""Spec 43 T1-T5 — scripted isolation tests against restart-api.py (before deploy).

Runs the module in a sandbox (temp dirs, mocked supervisorctl + /proc pid).
Fails loudly on any isolation violation.
"""
import json
import os
import shutil
import sys
import tempfile
import types

# ---- sandbox env (must precede import) -------------------------------
TMP = tempfile.mkdtemp(prefix="iso-test-")
os.environ["PROFILE_DIR"] = os.path.join(TMP, "profile")
os.environ["DOWNLOADS_DIR"] = os.path.join(TMP, "downloads")
os.environ["SESSIONS_DIR"] = os.path.join(TMP, "sessions")
os.environ["LISTEN_PORT"] = "19230"
os.environ["IDLE_ACTION"] = "suspend"
os.environ["IDLE_CHECK_INTERVAL"] = "999999"
os.environ["WATCHDOG_SECS"] = "999999"

import importlib.util

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "restart_api", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "restart-api.py"))
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)

# ---- mocks -------------------------------------------------------------
CALLS = []
CHROME_RUNNING = {"chrome": True, "title": True}
FAKE_PID = 4242


class FakeProc:
    returncode = 0
    stdout = ""
    stderr = ""


def fake_run(cmd, **kw):
    CALLS.append(list(cmd))
    # supervisorctl <action> <program>
    if len(cmd) >= 3:
        action, prog = cmd[1], cmd[2]
        if action == "stop" and prog == ra.CHROME_PROG:
            CHROME_RUNNING["chrome"] = False
        if action == "stop" and prog == ra.TITLE_PROXY_PROG:
            CHROME_RUNNING["title"] = False
        if action == "start" and prog == ra.CHROME_PROG:
            CHROME_RUNNING["chrome"] = True
        if action == "start" and prog == ra.TITLE_PROXY_PROG:
            CHROME_RUNNING["title"] = True
    return FakeProc()


ra.subprocess.run = fake_run
ra._chrome_main_pid = lambda: FAKE_PID


def sup_status():
    st = {}
    st[ra.CHROME_PROG] = "RUNNING" if CHROME_RUNNING["chrome"] else "STOPPED"
    st[ra.TITLE_PROXY_PROG] = "RUNNING" if CHROME_RUNNING["title"] else "STOPPED"
    return st


ra.sup_status = sup_status

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


def mk_user_archive(user, with_marker=None, urls=None):
    """Create an archive dir for `user` in the sandbox sessions dir."""
    d = os.path.join(ra.SESSIONS_DIR, user)
    p = os.path.join(d, "profile", "Default")
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(d, "profile", "tab-snapshot.json"), "w") as f:
        json.dump({"ts": 1, "urls": urls or ["https://example.com/" + user]}, f)
    if with_marker:
        with open(os.path.join(d, ".archive-user.json"), "w") as f:
            json.dump({"user": with_marker, "ts": 1}, f)
    return d


# ---- T5: archive_user writes owner marker ------------------------------
ra.set_slot_user("alice@x.pro", slot=1)
CHROME_RUNNING["chrome"] = True
# Spec 55 guard: archive_user refuses an empty on-disk profile (no
# Default/Preferences) — seed a real profile so the archive is accepted.
os.makedirs(os.path.join(ra.PROFILE, "Default"), exist_ok=True)
with open(os.path.join(ra.PROFILE, "Preferences"), "w") as f:
    f.write("{}")
ok = ra.archive_user("alice@x.pro")
m = os.path.join(ra.SESSIONS_DIR, "alice@x.pro", ".archive-user.json")
marker_ok = os.path.isfile(m) and json.load(open(m)).get("user") == "alice@x.pro"
check("T5 archive marker written", ok and marker_ok)

# ---- T4: restore_user refuses mismatched marker ------------------------
mk_user_archive("bob@x.pro", with_marker="alice@x.pro")
res = ra.restore_user("bob@x.pro")
check("T4 marker mismatch refused", res is False)

# ---- T1: do_wake same-user no-op ---------------------------------------
mk_user_archive("alice@x.pro", with_marker="alice@x.pro")
ra.set_slot_user("alice@x.pro", slot=1)
CHROME_RUNNING["chrome"] = True
CALLS.clear()
r = ra.do_wake("alice@x.pro")
no_restore_call = not any("restore" in " ".join(c).lower() for c in CALLS)
# Spec 72: same-user wake with zero real tabs returns "restore requested"
# (a harmless in-process CDP restore) rather than the legacy "already up";
# either way Chrome must stay up and NO supervisorctl stop/start may fire.
no_lifecycle = not any(c and c[1] in ("stop", "start") for c in CALLS)
check("T1 same-user no-op",
      r.get("ok") is True and CHROME_RUNNING["chrome"]
      and r.get("note") in ("already up", "restore requested")
      and no_restore_call and no_lifecycle,
      str(CALLS))

# ---- T2: do_wake user switch stops chrome before restore ---------------
mk_user_archive("carol@x.pro", with_marker="carol@x.pro")
ra.set_slot_user("alice@x.pro", slot=1)
CHROME_RUNNING["chrome"] = True
CHROME_RUNNING["title"] = True
CALLS.clear()
r = ra.do_wake("carol@x.pro")
stop_idx = next((i for i, c in enumerate(CALLS)
                 if c and len(c) >= 2 and c[1] == "stop"), -1)
restore_after_stop = stop_idx >= 0 and ra.slot_user() == "carol@x.pro"
check("T2 user-switch stops chrome + restores", restore_after_stop and ra.slot_user() == "carol@x.pro",
      str(CALLS))

# ---- T3: do_suspend pid guard skips snapshot ---------------------------
# Force chrome to NOT own the profile: start for carol, then claim slot
# user is alice (foreign process simulation).
ra.set_slot_user("alice@x.pro", slot=1)
ra._started_for_user = "carol@x.pro"  # chrome started for someone else
ra._started_pid = FAKE_PID
snap = os.path.join(ra.PROFILE, "tab-snapshot.json")
with open(snap, "w") as f:
    f.write("stale")
ra._suspended = False
ra.do_suspend(reason="test")
guard_fired = not os.path.exists(snap)
check("T3 suspend guard clears stale snapshot", guard_fired)
check("T3 suspend archived (release still happened)",
      os.path.isdir(os.path.join(ra.SESSIONS_DIR, "alice@x.pro")))

# ---- T1b: do_wake same user with chrome DOWN still starts --------------
ra.set_slot_user("carol@x.pro", slot=1)
CHROME_RUNNING["chrome"] = False
CALLS.clear()
r = ra.do_wake("carol@x.pro")
check("T1b same-user chrome-down starts chrome",
      CHROME_RUNNING["chrome"] and r.get("ok") is True)

print(f"\n== {len(PASS)} passed, {len(FAIL)} failed ==")
if FAIL:
    print("FAILED:", FAIL)
    sys.exit(1)
print("ALL SCRIPTED ISOLATION TESTS GREEN")
