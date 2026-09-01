#!/usr/bin/env python3
"""GrantHub router endpoint tests (spec 47 GH.2/GH.5/GH.6).

Boots the real router (bootstrap monkeypatch, no slot traffic needed — the
/connect* endpoints are in-process) against a scratch GRANT_ROOT and
exercises the full API surface:

  GET  /connect                     → 200 page (email) / 401 (none)
  GET  /connect/status              → shared:false → true after grant
  POST /connect/grant               → 501 no token / 403 bad / 200 good
  POST /connect/revoke              → shared:false; unwrap refuses
  POST /connect/admin/revoke-all    → 501/403/200, revokes every user
  pill state (_shared_state)        → follows the store, no false green
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROUTER_PORT = 18099
ROUTER = "http://127.0.0.1:%d" % ROUTER_PORT
ROUTER2 = "http://127.0.0.1:18100"
ST = "/tmp/gh-router-state.json"
GRANTS = "/tmp/gh-router-grants"
BROKER, ADMIN = "test-broker-token", "test-admin-token"


def boot(port=ROUTER_PORT, st=ST, grants=GRANTS, broker=BROKER, admin=ADMIN):
    env = dict(os.environ)
    env.update({
        "ROUTER_PORT": str(port),
        "ROUTER_STATE": st,
        "N_SLOTS": "1", "AUTO_CREATE_SESSIONS": "true",
        "CB_HUMAN_SLOTS": "1", "CB_AGENT_SLOTS": "0",
        "CB_HUMAN_MAX_SESSION_MIN": "240", "CB_AGENT_MAX_SESSION_MIN": "240",
        "CB_QUEUE_POLL_INTERVAL_S": "5", "CB_REAPER_INTERVAL_S": "60",
        "CB_AGENT_TOKEN": "test-token", "NEKO_PASSWORD": "neko",
        "SLOT_PORT": "18090", "FILES_PORT": "18090",
        "GRANT_ROOT": grants,
        "CB_GRANTHUB_BROKER_TOKEN": broker,
        "CB_GRANTHUB_ADMIN_TOKEN": admin,
        "GRANTHUB_STATUS_URL": "",
    })
    return subprocess.Popen(
        [sys.executable, "/opt/data/router-bootstrap.py"], env=env,
        stdout=open("/tmp/gh-router.log", "a"), stderr=subprocess.STDOUT,
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


def req2(method, path, email=None, body=None, token=None):
    r = urllib.request.Request(ROUTER2 + path, method=method)
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


def main():
    for p in (ST, GRANTS):
        if os.path.isdir(p):
            shutil.rmtree(p)
        if os.path.isfile(p):
            os.unlink(p)
    proc = boot()
    passed, failed = [], []

    def check(name, cond, detail=""):
        (passed if cond else failed).append(name)
        print(("PASS " if cond else "FAIL ") + name
              + (f" — {detail}" if detail and not cond else ""))

    # wait for /health
    for _ in range(40):
        try:
            urllib.request.urlopen(ROUTER + "/health", timeout=2)
            break
        except Exception:
            time.sleep(0.25)

    E = "spike-user@aikumi.pro"

    # --- GET /connect ---
    code, body = req("GET", "/connect", email=E)
    check("GH GET /connect page (email)", code == 200 and "GrantHub" in body
          and "Revoke grant" in body)
    code, _ = req("GET", "/connect")
    check("GH GET /connect 401 without email", code == 401)

    # --- status before grant ---
    code, body = req("GET", "/connect/status", email=E)
    check("GH status initial shared:false",
          code == 200 and json.loads(body)["shared"] is False)

    # --- grant: fail closed ---
    # (token configured → no/wrong token = 403; the 501 "token unset" path
    # is covered by the tokenless instance at the end)
    code, _ = req("POST", "/connect/grant", email=E,
                  body={"key": "aGVsbG8gd29ybGQ="})
    check("GH grant 403 without broker token", code == 403)
    code, _ = req("POST", "/connect/grant", email=E,
                  body={"key": "aGVsbG8gd29ybGQ="}, token="wrong")
    check("GH grant 403 with bad token", code == 403)

    # --- grant: success ---
    code, body = req("POST", "/connect/grant", email=E,
                     body={"key": "aGVsbG8gd29ybGQ="}, token=BROKER)
    j = json.loads(body)
    check("GH grant 200 + shared:true", code == 200 and j.get("shared") is True)
    gdir = os.path.join(GRANTS, E, "grant")
    check("GH grant files on disk",
          os.path.exists(os.path.join(gdir, "grant.json"))
          and os.path.exists(os.path.join(gdir, "k_user.bin")))
    import stat as _st
    mode = _st.S_IMODE(os.stat(os.path.join(gdir, "grant.json")).st_mode)
    check("GH grant.json 0600", mode == 0o600)
    check("GH grant.json has no plaintext key",
          "aGVsbG8gd29ybGQ=" not in open(os.path.join(gdir, "grant.json")).read())

    # --- status + unwrap roundtrip via the shared lib ---
    sys.path.insert(0, "/opt/data")
    import granthub
    code, body = req("GET", "/connect/status", email=E)
    check("GH status shared:true after grant",
          json.loads(body)["shared"] is True)
    check("GH unwrap roundtrip == original key",
          granthub.unwrap(GRANTS, E) == "aGVsbG8gd29ybGQ=")

    # --- spec 59: session-token leg + usable gating ---
    code, body = req("GET", "/connect/status", email=E)
    j = json.loads(body)
    check("GH59 key-only grant: shared:true usable:false session:false",
          code == 200 and j["shared"] is True and j["usable"] is False
          and j["session"] is False)
    code, _ = req("POST", "/connect/grant", email="no-grant@x.pro",
                  body={"session": "sess-token-abc"}, token=BROKER)
    check("GH59 session-only upgrade 400 without existing grant", code == 400)
    code, body = req("POST", "/connect/grant", email=E,
                     body={"session": "refresh-token-123"}, token=BROKER)
    j = json.loads(body)
    check("GH59 session upgrade 200 + usable:true session:true",
          code == 200 and j["usable"] is True and j["session"] is True
          and j["shared"] is True)
    check("GH59 unwrap_session roundtrip == original token",
          granthub.unwrap_session(GRANTS, E) == "refresh-token-123")
    with open(os.path.join(gdir, "grant.json")) as f:
        raw_grant = f.read()
    check("GH59 grant.json holds no plaintext session token",
          "refresh-token-123" not in raw_grant)
    # A deliberately cleared/stale session leg is an expected recovery state,
    # not an uncaught AssertionError that drops the router connection.
    with open(os.path.join(gdir, "grant.json")) as f:
        missing = json.load(f)
    missing["wrapped_session"] = None
    with open(os.path.join(gdir, "grant.json"), "w") as f:
        json.dump(missing, f)
    try:
        granthub.unwrap_session(GRANTS, E)
        missing_leg_closed = False
    except granthub.GrantError as exc:
        missing_leg_closed = str(exc) == "session leg missing"
    check("GH59 missing session leg fails closed as GrantError",
          missing_leg_closed)
    code, _ = req("POST", "/connect/grant", email=E,
                  body={"session": "refresh-token-123"}, token=BROKER)
    check("GH59 session leg restores after deliberate clear", code == 200)
    code, body = req("POST", "/connect/grant", email="fresh@x.pro",
                     body={"key": "aGVsbG8gd29ybGQ=", "session": "rt-fresh"},
                     token=BROKER)
    j = json.loads(body)
    check("GH59 combined key+session grant usable:true",
          code == 200 and j["usable"] is True)
    check("GH59 unwrap works for combined grant",
          granthub.unwrap(GRANTS, "fresh@x.pro") == "aGVsbG8gd29ybGQ=")
    req("POST", "/connect/grant", email="key-only@x.pro",
        body={"key": "aGVsbG8gd29ybGQ="}, token=BROKER)

    # --- pill state follows the store ---
    import importlib.util
    os.environ["GRANT_ROOT"] = GRANTS  # the module reads env at import time
    spec = importlib.util.spec_from_file_location("router", "/opt/data/router.py")
    rmod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(rmod)
        label, cls = rmod._shared_state(E)
        check("GH59 pill NOT green for key+session-usable grant is green",
              label == "🔗 Shared" and cls == "cb-shared")
        label0, cls0 = rmod._shared_state("key-only@x.pro")
        check("GH59 pill red for key-only grant (usable gate)",
              label0 == "🔗 Not Shared" and cls0 == "cb-noshared")
        label2, cls2 = rmod._shared_state("nobody@x.pro")
        check("GH pill Not Shared/red for others",
              label2 == "🔗 Not Shared" and cls2 == "cb-noshared")
        label3, cls3 = rmod._shared_state("fresh@x.pro")
        check("GH59 pill Shared/green only when usable (combined grant)",
              label3 == "🔗 Shared" and cls3 == "cb-shared")
    except Exception as e:
        check("GH pill state module load", False, str(e))

    # --- revoke: user self-service ---
    code, body = req("POST", "/connect/revoke", email=E)
    j = json.loads(body)
    check("GH revoke 200 + shared:false", code == 200 and j["shared"] is False)
    try:
        granthub.unwrap(GRANTS, E)
        check("GH unwrap refuses after revoke", False)
    except granthub.GrantError:
        check("GH unwrap refuses after revoke", True)
    try:
        granthub.unwrap_session(GRANTS, E)
        check("GH59 unwrap_session refuses after revoke", False)
    except granthub.GrantError:
        check("GH59 unwrap_session refuses after revoke", True)
    code, body = req("GET", "/connect/status", email=E)
    check("GH status stays false after revoke",
          json.loads(body)["shared"] is False)

    # --- admin revoke-all ---
    for who, key in [("admin-a@x.pro", "YWE="), ("admin-b@x.pro", "YmI=")]:
        req("POST", "/connect/grant", email=who, body={"key": key}, token=BROKER)
    code, _ = req("POST", "/connect/admin/revoke-all", token="wrong")
    check("GH admin 403 bad token", code == 403)
    code, _ = req("POST", "/connect/admin/revoke-all")
    check("GH admin 403 no token", code == 403)
    code, body = req("POST", "/connect/admin/revoke-all", token=ADMIN)
    j = json.loads(body)
    # 5 grant files exist at this point (E's already-revoked one, the
    # combined-grant user fresh@x.pro, key-only@x.pro, plus the two
    # admins) — revoke_all re-marks every store record.
    check("GH admin revoke-all 200 + count 5",
          code == 200 and j.get("revoked") == 5)
    st1 = json.loads(req("GET", "/connect/status", email="admin-a@x.pro")[1])
    st2 = json.loads(req("GET", "/connect/status", email="admin-b@x.pro")[1])
    check("GH admin revoke-all bit both", st1["shared"] is False and st2["shared"] is False)
    check("GH status 401 without email",
          req("GET", "/connect/status")[0] == 401)
    check("GH unknown path 404",
          req("GET", "/connect/bogus", email=E)[0] == 404)

    # --- fail closed when tokens are NOT configured (separate instance) ---
    proc.terminate()
    proc.wait(timeout=10)
    ST2, G2 = "/tmp/gh-router-state2.json", "/tmp/gh-router-grants2"
    for p in (ST2, G2):
        if os.path.isdir(p):
            shutil.rmtree(p)
        if os.path.isfile(p):
            os.unlink(p)
    proc2 = boot(port=18100, st=ST2, grants=G2, broker="", admin="")
    for _ in range(40):
        try:
            urllib.request.urlopen("http://127.0.0.1:18100/health", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    code, _ = req2("POST", "/connect/grant", email=E, body={"key": "eA=="})
    check("GH grant 501 when broker token unset", code == 501)
    code, _ = req2("POST", "/connect/admin/revoke-all")
    check("GH admin 501 when admin token unset", code == 501)
    proc2.terminate()
    proc2.wait(timeout=10)
    print(f"\nRESULT: {len(passed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
