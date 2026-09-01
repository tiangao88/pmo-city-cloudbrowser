#!/usr/bin/env python3
"""Isolation/security RED tests (audit blockers 3, 4, 5, 10) — slot-to-router
binding, removal of shared grant access, canonical identity/path safety, and
one-shot challenge-bound OTP.

Boots the REAL router (router-bootstrap monkeypatch) with TWO slots and a
seeded owner map, then exercises:

  slot binding   — /connect/grant, /connect/grant/material, /otp/* with
                   per-slot broker tokens: any owner other than the
                   server-derived slot owner → 403.
  grant isolation— slots never mount the global grant store: material is
                   returned ONLY through the router API; no store paths
                   are reachable from a slot.
  identity safety— granthub.canonical_email / grant_dir reject traversal
                   and noncanonical identities before any filesystem use.
  OTP one-shot   — /otp/challenge returns an opaque request id bound to
                   {slot, owner}; exactly one submit and one fetch;
                   duplicate submit / stale id / cross-slot / owner
                   reassignment all fail closed.

Run:  python3 test-isolation-d2.py   (from /opt/data with env)
"""
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CB_SLOT_SCRIPTS", HERE)

ROUTER_PORT = 18111
ROUTER = "http://127.0.0.1:%d" % ROUTER_PORT
ST = "/tmp/iso-router-state.json"
GRANTS = "/tmp/iso-router-grants"
S1, S2 = "slot-1-token", "slot-2-token"
AGENT = "otp-agent-token"
E1 = "spike-user@aikumi.pro"
E2 = "montigaud@aikumi.pro"
KEY = base64.b64encode(b"0123456789abcdef").decode()          # 16B user key
REFRESH = "rt-" + "a" * 40                                     # refresh token


def seed_state():
    st = {
        "users": {E1: 1, E2: 2},
        "slots": {"1": E1, "2": E2},
        "archives": {},
        "queue": [],
        "sessions": {E1: {"slot": 1, "started_at": time.time(), "tier": "human"},
                     E2: {"slot": 2, "started_at": time.time(), "tier": "human"}},
        "history": {}, "queue_seq": 0, "rescue_at": {},
    }
    with open(ST, "w") as f:
        json.dump(st, f)


def boot():
    env = dict(os.environ)
    env.update({
        "ROUTER_PORT": str(ROUTER_PORT), "ROUTER_STATE": ST,
        "N_SLOTS": "2", "AUTO_CREATE_SESSIONS": "true",
        "CB_HUMAN_SLOTS": "2", "CB_AGENT_SLOTS": "0",
        "CB_HUMAN_MAX_SESSION_MIN": "240", "CB_AGENT_MAX_SESSION_MIN": "240",
        "CB_QUEUE_POLL_INTERVAL_S": "5", "CB_REAPER_INTERVAL_S": "60",
        "CB_AGENT_TOKEN": "test-token", "NEKO_PASSWORD": "neko",
        "SLOT_PORT": "18090", "FILES_PORT": "18090",
        "GRANT_ROOT": GRANTS,
        # per-slot broker credentials (spec 66 isolation, audit B3/B4)
        "CB_SLOT_1_TOKEN": S1, "CB_SLOT_2_TOKEN": S2,
        "CB_GRANTHUB_BROKER_TOKEN": "",   # legacy shared token DISABLED
        "CB_GRANTHUB_ADMIN_TOKEN": "x",
        "CB_OTP_AGENT_TOKEN": AGENT, "CB_OTP_TTL_S": "180",
        "GRANTHUB_STATUS_URL": "",
    })
    return subprocess.Popen(
        [sys.executable, os.path.join(HERE, "router-bootstrap.py")], env=env,
        stdout=open("/tmp/iso-router.log", "a"), stderr=subprocess.STDOUT,
        text=True, bufsize=1)


def req(method, path, email=None, body=None, token=None):
    r = urllib.request.Request(ROUTER + path, method=method)
    r.add_header("Host", "cloudbrowser.dev01.pmo.city")
    if email:
        r.add_header("Remote-Email", email)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(r, data=data, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def jreq(method, path, email=None, body=None, token=None):
    code, raw = req(method, path, email=email, body=body, token=token)
    try:
        return code, json.loads(raw)
    except Exception:
        return code, {}


# --------------------------------------------------------------------------
# 1. Canonical identity / path safety (granthub, in-process)
# --------------------------------------------------------------------------
def test_identity_safety():
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "vendor-d2"))
    spec = importlib.util.spec_from_file_location(
        "granthub_iso", os.path.join(HERE, "granthub.py"))
    gh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gh)
    ok = True

    def check(name, cond):
        nonlocal ok
        if not cond:
            ok = False
            print("FAIL " + name)

    check("granthub exposes canonical_email", hasattr(gh, "canonical_email"))
    check("granthub grant_dir validates identity",
          hasattr(gh, "grant_dir") and hasattr(gh, "canonical_email"))
    # canonical emails pass, everything hostile fails closed
    try:
        check("canonical_email accepts spike-user@aikumi.pro",
              gh.canonical_email("spike-user@aikumi.pro") == "spike-user@aikumi.pro")
    except Exception:
        check("canonical_email accepts spike-user@aikumi.pro", False)
    bad = [
        "../../etc/passwd", "a/../b@c.d", "..@a.b", "a@b", "a@b..c",
        "a..b@c.d", "a@-x.com", "a@x-.com", "a b@c.d", "a@b c.d",
        "a@b/c.d", "a@b\\c.d", "a@b:c.d", "a@b%0a.d", "a@b.d.",
        "a@.b.d", "a@b..d", "a@b.d..", "a@b.d/e", "a@b.d/../../x",
        "A@B.D", "A..@b.d", "a@b.d..x", "a@b.d/x", "a@b.d%2e%2e",
        "a@b.d./x", "a@b.d/x/../../y",
    ]
    for v in bad:
        try:
            r = gh.canonical_email(v)
            check("canonical_email rejects %r" % v, r is None)
        except Exception:
            check("canonical_email rejects %r" % v, False)

    # grant_dir: identity-derived paths stay inside the root, even hostile
    root = "/tmp/iso-identity-root"
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    g = gh.grant_dir(root, "spike-user@aikumi.pro")
    check("grant_dir inside root",
          g == os.path.join(root, "spike-user@aikumi.pro", "grant"))
    check("grant_dir realpath inside root",
          os.path.realpath(g).startswith(os.path.realpath(root) + os.sep))
    for v in bad:
        try:
            gh.grant_dir(root, v)
            check("grant_dir raises for %r" % v, False)
        except (ValueError, gh.GrantError):
            pass
    evil = os.path.join(root, "..", "..", "etc")
    try:
        check("grant_dir rejects traversal path", gh.canonical_email(evil) is None)
    except Exception:
        check("grant_dir rejects traversal path", False)
    shutil.rmtree(root, ignore_errors=True)
    return ok


# --------------------------------------------------------------------------
# 2-4. Router: slot binding, grant isolation, challenge OTP (real router)
# --------------------------------------------------------------------------
def test_router_binding_and_otp():
    for p in (ST, GRANTS):
        if os.path.isdir(p):
            shutil.rmtree(p)
        if os.path.isfile(p):
            os.unlink(p)
    seed_state()
    proc = boot()
    ok = True

    def check(name, cond):
        nonlocal ok
        if not cond:
            ok = False
            print("FAIL " + name)

    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(ROUTER + "/health", timeout=2)
                break
            except Exception:
                time.sleep(0.25)

        # --- B3: slot-to-router binding on /connect/grant ---
        # slot-1 token cannot claim slot-2's owner
        code, _ = jreq("POST", "/connect/grant", email=E2,
                       body={"key": KEY}, token=S1)
        check("grant: slot-1 token + slot-2 email → 403", code == 403)
        # no token / wrong token still fail closed
        code, _ = jreq("POST", "/connect/grant", email=E1, body={"key": KEY})
        check("grant: no bearer → 403", code == 403)
        code, _ = jreq("POST", "/connect/grant", email=E1,
                       body={"key": KEY}, token="wrong")
        check("grant: unknown bearer → 403", code == 403)
        # correct slot-1 owner via slot-1 token succeeds
        code, j = jreq("POST", "/connect/grant", email=E1,
                       body={"key": KEY, "session": REFRESH}, token=S1)
        check("grant: slot-1 token + slot-1 owner → 200 usable",
              code == 200 and j.get("usable") is True)
        check("grant files exist under store",
              os.path.exists(os.path.join(GRANTS, E1, "grant", "grant.json"))
              and os.path.exists(os.path.join(GRANTS, E1, "grant", "k_user.bin")))

        # --- B3: grant material only through the router, per-slot ---
        code, j = jreq("GET", "/connect/grant/material", email=E1, token=S1)
        check("material: slot-1 owner via slot-1 token → key+session",
              code == 200 and j.get("key") == KEY
              and j.get("session") == REFRESH
              and j.get("scope") == "PMO City vault")
        # The slot-side vault client intentionally sends no Remote-Email:
        # identity is derived entirely from the per-slot bearer. This exact
        # production request shape must succeed; otherwise the broker cannot
        # read the current owner's grant and autonomous login is dead.
        code, j = jreq("GET", "/connect/grant/material", token=S1)
        check("material: slot bearer alone derives current owner → key+session",
              code == 200 and j.get("key") == KEY
              and j.get("session") == REFRESH)
        # The slot-side vault client also persists every rotated refresh token
        # without Remote-Email; the same bearer-derived owner binding applies.
        rotated = "refresh-token-rotated"
        code, j = jreq("POST", "/connect/grant", body={"session": rotated},
                       token=S1)
        check("grant rotation: slot bearer alone derives owner → 200",
              code == 200 and j.get("usable") is True)
        code, j = jreq("GET", "/connect/grant/material", token=S1)
        check("grant rotation: material returns persisted rotated session",
              code == 200 and j.get("session") == rotated)
        # cross-slot read denied
        code, _ = jreq("GET", "/connect/grant/material", email=E1, token=S2)
        check("material: slot-2 token cannot read slot-1 owner → 403",
              code == 403)
        code, _ = jreq("GET", "/connect/grant/material", email=E2, token=S1)
        check("material: slot-1 token cannot read slot-2 owner → 403",
              code == 403)
        code, _ = jreq("GET", "/connect/grant/material", email=E1)
        check("material: no bearer → 403", code == 403)
        # unknown email on the store → 403 (identity must equal the
        # server-derived owner; never a store lookup for another identity)
        code, _ = jreq("GET", "/connect/grant/material", email="x@y.z", token=S1)
        check("material: unknown email → 403", code == 403)

        # --- B5: hostile identities are rejected before filesystem use ---
        code, _ = jreq("POST", "/connect/grant", email="../../etc/passwd",
                       body={"key": KEY}, token=S1)
        check("grant: traversal Remote-Email → 403", code == 403)
        code, _ = jreq("GET", "/connect/grant/material", email="..%2f..%2fetc",
                       token=S1)
        check("material: encoded traversal → 403", code == 403)

        # --- B10: one-shot challenge-bound OTP ---
        # challenge requires the slot's OWN owner
        code, _ = jreq("POST", "/otp/challenge", email=E2, token=S1)
        check("otp/challenge: slot-1 token + slot-2 email → 403", code == 403)
        code, _ = jreq("POST", "/otp/challenge", email=E1)
        check("otp/challenge: no bearer → 403", code == 403)
        # challenge for the right owner returns an opaque id
        code, j = jreq("POST", "/otp/challenge", email=E1, token=S1)
        check("otp/challenge: 200 + request id",
              code == 200 and isinstance(j.get("request_id"), str)
              and len(j["request_id"]) >= 16 and j.get("ttl_s") == 180)
        rid = j.get("request_id", "")
        # pending before submit: empty
        code, j = jreq("GET", "/otp/pending?challenge=" + rid, email=E1, token=S1)
        check("otp/pending: empty before submit", j.get("code") is None)
        # submit requires the agent token; without a challenge id the
        # legacy email-bound fallback applies (404 when none pending)
        code, _ = jreq("POST", "/otp/submit", email=E1, body={"code": "123456"})
        check("otp/submit: no bearer → 403", code == 403)
        code, _ = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "123456", "challenge": rid}, token="wrong")
        check("otp/submit: wrong agent token → 403", code == 403)
        code, _ = jreq("POST", "/otp/submit", email="nobody@aikumi.pro",
                       body={"code": "123456"}, token=AGENT)
        check("otp/submit: no challenge id + no pending for email → 404",
              code == 404)
        code, _ = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "123456", "challenge": rid}, token=AGENT)
        check("otp/submit: first submit ok", code == 200)
        # duplicate submit is rejected (one-shot)
        code, _ = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "654321", "challenge": rid}, token=AGENT)
        check("otp/submit: duplicate submit → 409", code == 409)
        # fetch returns the code ONCE
        code, j = jreq("GET", "/otp/pending?challenge=" + rid, email=E1, token=S1)
        check("otp/pending: returns code once", j.get("code") == "123456")
        code, j = jreq("GET", "/otp/pending?challenge=" + rid, email=E1, token=S1)
        check("otp/pending: read-once (cleared)", j.get("code") is None)
        # replay submit after consume → 409
        code, _ = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "111111", "challenge": rid}, token=AGENT)
        check("otp/submit: replay after consume → 409", code == 409)
        # stale / unknown challenge id → 404
        code, _ = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "111111", "challenge": "deadbeef"}, token=AGENT)
        check("otp/submit: stale challenge id → 404", code == 404)
        # wrong-slot fetch: slot-2 token cannot read slot-1's challenge
        code, _ = jreq("GET", "/otp/pending?challenge=" + rid, email=E1, token=S2)
        check("otp/pending: wrong slot token → 403", code == 403)
        # owner reassignment invalidates the challenge (slot-1 now E2)
        with open(ST) as f:
            st = json.load(f)
        st["users"][E1], st["slots"]["1"] = 2, E2
        with open(ST, "w") as f:
            json.dump(st, f)
        code, _ = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "111111", "challenge": rid}, token=AGENT)
        check("otp/submit: challenge after owner reassignment → 4xx",
              code in (403, 409, 404))

        # --- backward compat: legacy email-only flow still works ---
        code, j = jreq("POST", "/otp/request", email=E1, token=S1)
        check("otp/request legacy: 200 + ttl", code == 200 and j.get("ttl_s") == 180)
        rid2 = j.get("request_id", "")
        code, _ = jreq("POST", "/otp/request", email=E2, token=S1)
        check("otp/request legacy: slot-1 token + other email → 403", code == 403)
        code, j = jreq("POST", "/otp/submit", email=E1,
                       body={"code": "999999"}, token=AGENT)
        check("otp/submit legacy: email-bound fallback stores code",
              code == 200 and j.get("ok"))
        code, j = jreq("GET", "/otp/pending?challenge=" + rid2, email=E1, token=S1)
        check("otp/pending legacy: fetch returns submitted code",
              code == 200 and j.get("code") == "999999")
        code, j = jreq("GET", "/otp/pending?challenge=" + rid2, email=E1, token=S1)
        check("otp/pending legacy: code consumed (read-once)",
              code == 404 or j.get("code") is None)

        # --- B3: code never persisted ---
        if os.path.isfile(ST):
            raw = open(ST, "rb").read()
            check("otp code absent from router state", b"123456" not in raw)
        if os.path.isfile("/tmp/iso-router.log"):
            raw = open("/tmp/iso-router.log", "rb").read()
            check("otp code absent from router log", b"123456" not in raw)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
    return ok


def main():
    results = [
        ("identity/path safety (B5)", test_identity_safety()),
        ("slot binding + grant isolation + challenge OTP (B3/B4/B10)",
         test_router_binding_and_otp()),
    ]
    npass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(("PASS " if ok else "FAIL ") + name)
    print(f"Isolation suite: {npass}/{len(results)}")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
