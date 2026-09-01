#!/usr/bin/env python3
"""D2 hybrid-2FA tests (spec 73) — TOTP math, vault-client, broker MFA
decision, router OTP code-exchange endpoints.

Local only: no live vault, no live slots. The router is booted in-process
style via router-bootstrap (test-granthub pattern); vault-client and totp
are pure; sso-broker MFA decision functions are imported via importlib
with urlopen stubbed.

Run:  python3 test-d2.py   (from the scripts dir or /opt/data with env)
"""
import base64
import hashlib
import hmac
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
# vault-client and sso-broker resolve their slot-side libs (gcm, pyaes)
# relative to CB_SLOT_SCRIPTS — point them at this test directory.
os.environ.setdefault("CB_SLOT_SCRIPTS", HERE)
OTP_PENDING_URL_BASE = "http://router:8081/otp/pending"

# --------------------------------------------------------------------------
# TOTP (RFC 6238)
# --------------------------------------------------------------------------
def test_totp():
    sys.path.insert(0, HERE)
    import totp
    sec = "12345678901234567890"          # RFC 6238 appendix B test key
    b32 = base64.b32encode(sec.encode()).decode()
    vectors = [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ]
    ok = True
    for t, expect in vectors:
        # RFC 6238 appendix-B vectors are 8-digit codes
        got = totp.totp(b32, at=t, digits=8)
        if got != expect:
            print(f"FAIL totp RFC vector t={t}: got {got} want {expect}")
            ok = False
    return ok

def test_totp_secret_parsing():
    sys.path.insert(0, HERE)
    import totp
    ok = True
    # otpauth URL
    u = "otpauth://totp/Authentik:spike-user?secret=GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&issuer=Authentik"
    if totp.normalize_secret(u) != "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ":
        print("FAIL normalize otpauth url"); ok = False
    # base32 with spaces + lowercase
    if totp.normalize_secret("gezd gnbv gy3t qojq gezd gnbv gy3t qojq") != "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ":
        print("FAIL normalize spaced b32"); ok = False
    # non-base32 raw fallback
    if totp.normalize_secret("not-base32!") != "NOT-BASE32!":
        print("FAIL normalize raw fallback"); ok = False
    # deterministic across calls at same time
    t = time.time()
    a = totp.totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=t)
    b = totp.totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=t)
    if a != b or len(a) != 6 or not a.isdigit():
        print("FAIL determinism/digits"); ok = False
    return ok

# --------------------------------------------------------------------------
# vault-client
# --------------------------------------------------------------------------
def _enc(plain, key64, mac_key=None):
    """Encrypt a plaintext into a Bitwarden encType-2 EncString (test helper)."""
    from pyaes import AESModeOfOperationCBC, Encrypter  # noqa: F401
    iv = b"\x01" * 16
    mode = AESModeOfOperationCBC(key64[0:32], iv)
    en = Encrypter(mode)
    ct = en.feed(plain.encode()) + en.feed()
    mk = mac_key or key64[32:64]
    mac = hmac.new(mk, iv + ct, hashlib.sha256).digest()
    b = base64.b64encode
    return "2." + b(iv).decode() + "|" + b(ct).decode() + "|" + b(mac).decode()

def _selection_error(fn):
    try:
        fn()
    except Exception as exc:
        return type(exc).__name__ == "VaultItemSelectionError"
    return False


def test_vault_client():
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.join(HERE, "vendor"))
    import vault_client
    key64 = bytes(range(64))
    ok = True
    # encstring roundtrip
    plain = vault_client.decrypt_encstring(_enc("hello world", key64), key64)
    if plain != "hello world":
        print("FAIL encstring roundtrip"); ok = False
    # plaintext passthrough
    if vault_client.decrypt_encstring("plaintext", key64) != "plaintext":
        print("FAIL plaintext passthrough"); ok = False
    # wrong key → raises
    try:
        vault_client.decrypt_encstring(_enc("hello", key64), bytes(64))
        print("FAIL wrong key did not raise"); ok = False
    except ValueError:
        pass
    # Exact, fail-closed SSO item selection.
    wanted = {"id": "b", "name": "Authentik Spike User",
              "uris": ["https://auth.aikumi.app/"], "username": "u",
              "password": "p", "totp_secret": None,
              "org_key_missing": False}
    if vault_client.find_ssologin([wanted], exact_name="Authentik Spike User") != wanted:
        print("FAIL exact SSO item selection"); ok = False
    bad_uri = dict(wanted, id="x", uris=["https://evil.example/?next=https://auth.aikumi.app/"])
    if not _selection_error(lambda: vault_client.find_ssologin([bad_uri], exact_name="Authentik Spike User")):
        print("FAIL deceptive SSO URI accepted"); ok = False
    duplicate = [dict(wanted, id="a"), dict(wanted, id="b")]
    if not _selection_error(lambda: vault_client.find_ssologin(duplicate, exact_name="Authentik Spike User")):
        print("FAIL duplicate SSO items accepted"); ok = False
    if vault_client.find_ssologin([wanted], item_id="b", exact_name=None) != wanted:
        print("FAIL SSO item ID selection"); ok = False
    # totp_secret priority: native > custom field > None
    if vault_client.totp_secret({"login": {"totp": "NATIVE"}, "fields": []}) != "NATIVE":
        print("FAIL totp native"); ok = False
    if vault_client.totp_secret(
            {"login": {}, "fields": [{"name": "TOTP", "value": "CUSTOM"}]}) != "CUSTOM":
        print("FAIL totp custom"); ok = False
    if vault_client.totp_secret(
            {"login": {}, "fields": [{"name": "Other", "value": "x"}]}) is not None:
        print("FAIL totp missing"); ok = False
    return ok

# --------------------------------------------------------------------------
# sso-broker MFA decision (importlib, urlopen stubbed)
# --------------------------------------------------------------------------
def _load_broker():
    spec = importlib.util.spec_from_file_location(
        "sso_broker_d2", os.path.join(HERE, "sso-broker.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class _Resp:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
    def read(self):
        return json.dumps(self.payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

def test_broker_mfa():
    os.environ["CB_GRANTHUB_BROKER_TOKEN"] = "test-broker-token"
    sb = _load_broker()
    ok = True
    calls = []
    _real_urlopen = urllib.request.urlopen
    def fake_urlopen(req, timeout=5):
        hdrs = {k.lower(): v for k, v in req.headers.items()}
        calls.append((req.full_url, req.get_method(),
                      hdrs.get("remote-email"),
                      hdrs.get("authorization"),
                      req.data))
        u = req.full_url
        if u.endswith("/otp/request"):
            return _Resp({"ok": True, "ttl_s": 180, "request_id": "ch-test-1"})
        if u.startswith(OTP_PENDING_URL_BASE):
            return _Resp({"code": "123456", "ttl_s": 180})
        raise AssertionError("unexpected url " + u)
    try:
        urllib.request.urlopen = fake_urlopen
        # no seed → request_code posts to /otp/request with broker Bearer + owner
        # and returns the challenge request id (audit B10 binding)
        rid = sb.request_code("spike-user@aikumi.pro")
        if not isinstance(rid, str) or not rid:
            print("FAIL request_code False"); ok = False
        if not calls or not calls[-1][0].endswith("/otp/request"):
            print("FAIL request_code url"); ok = False
        if calls[-1][2] != "spike-user@aikumi.pro":
            print("FAIL request_code Remote-Email"); ok = False
        if not str(calls[-1][3]).startswith("Bearer "):
            print("FAIL request_code bearer"); ok = False
        # fetch_code returns the code (read-once server-side), bound to the
        # challenge id
        code = sb.fetch_code("spike-user@aikumi.pro", rid)
        if code != "123456":
            print("FAIL fetch_code value"); ok = False
        if not calls or "challenge=" not in calls[-1][0]:
            print("FAIL fetch_code carries challenge id"); ok = False
        # decision: seed present → autonomous; absent → request path
        if not sb.mfa_autonomous(seed="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"):
            print("FAIL mfa_autonomous with seed"); ok = False
        if sb.mfa_autonomous(seed=None):
            print("FAIL mfa_autonomous without seed"); ok = False
    finally:
        urllib.request.urlopen = _real_urlopen
    return ok

# --------------------------------------------------------------------------
# Router OTP endpoints (boot the real router)
# --------------------------------------------------------------------------
ROUTER_PORT = 18101
ROUTER = "http://127.0.0.1:%d" % ROUTER_PORT
ST = "/tmp/d2-router-state.json"
GRANTS = "/tmp/d2-router-grants"
BROKER, AGENT = "d2-broker-token", "d2-agent-token"

def boot():
    env = dict(os.environ)
    env.update({
        "ROUTER_PORT": str(ROUTER_PORT),
        "ROUTER_STATE": ST,
        "N_SLOTS": "1", "AUTO_CREATE_SESSIONS": "true",
        "CB_HUMAN_SLOTS": "1", "CB_AGENT_SLOTS": "0",
        "CB_HUMAN_MAX_SESSION_MIN": "240", "CB_AGENT_MAX_SESSION_MIN": "240",
        "CB_QUEUE_POLL_INTERVAL_S": "5", "CB_REAPER_INTERVAL_S": "60",
        "CB_AGENT_TOKEN": "test-token", "NEKO_PASSWORD": "neko",
        "SLOT_PORT": "18090", "FILES_PORT": "18090",
        "GRANT_ROOT": GRANTS,
        "CB_GRANTHUB_BROKER_TOKEN": BROKER,
        "CB_GRANTHUB_ADMIN_TOKEN": "x",
        "CB_OTP_AGENT_TOKEN": AGENT,
        "CB_OTP_TTL_S": "180",
        "GRANTHUB_STATUS_URL": "",
    })
    return subprocess.Popen(
        [sys.executable, os.path.join(HERE, "router-bootstrap.py")], env=env,
        stdout=open("/tmp/d2-router.log", "a"), stderr=subprocess.STDOUT,
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

def jget(method, path, email=None, body=None, token=None):
    code, raw = req(method, path, email=email, body=body, token=token)
    try:
        return code, json.loads(raw)
    except Exception:
        return code, {}

def test_router_otp():
    for p in (ST, GRANTS):
        if os.path.isdir(p):
            shutil.rmtree(p)
        if os.path.isfile(p):
            os.unlink(p)
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
        E = "spike-user@aikumi.pro"
        # fail closed
        code, _ = jget("GET", "/otp/pending", email=E)
        check("otp pending 403 without broker token", code == 403)
        code, _ = jget("GET", "/otp/pending", email=E, token="wrong")
        check("otp pending 403 wrong broker token", code == 403)
        code, _ = jget("POST", "/otp/submit", email=E, body={"code": "123456"})
        check("otp submit 403 without agent token", code == 403)
        code, _ = jget("POST", "/otp/submit", email=E, body={"code": "123456"}, token="wrong")
        check("otp submit 403 wrong agent token", code == 403)
        # happy path
        code, j = jget("POST", "/otp/request", email=E, token=BROKER)
        check("otp request 200 + ttl", code == 200 and j.get("ok") and j.get("ttl_s") == 180)
        rid = j.get("request_id", "")
        check("otp request returns challenge id", isinstance(rid, str) and len(rid) >= 16)
        code, j = jget("GET", "/otp/pending?challenge=" + rid, email=E, token=BROKER)
        check("otp pending empty before submit", code == 200 and j.get("code") is None)
        code, j = jget("POST", "/otp/submit", email=E, body={"code": "123456"}, token=AGENT)
        check("otp submit 200", code == 200 and j.get("ok"))
        code, j = jget("GET", "/otp/pending?challenge=" + rid, email=E, token=BROKER)
        check("otp pending returns code once", code == 200 and j.get("code") == "123456")
        code, j = jget("GET", "/otp/pending?challenge=" + rid, email=E, token=BROKER)
        check("otp pending read-once (cleared)", code in (200, 404) and j.get("code") is None)
        # bad code rejected
        code, _ = jget("POST", "/otp/submit", email=E, body={"code": "abc"}, token=AGENT)
        check("otp submit rejects non-digit code", code == 400)
        # code never persisted to state file
        if os.path.isfile(ST):
            raw = open(ST, "rb").read()
            check("otp code absent from router state", b"123456" not in raw)
        # different user isolation
        code, j = jget("GET", "/otp/pending", email="montigaud@aikumi.pro", token=BROKER)
        check("otp pending isolated per user", j.get("code") is None)
        # TTL expiry (short TTL via second boot)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
    return ok

def test_router_otp_ttl():
    # boot a second router with a 1s TTL and verify expiry clears the code
    env = dict(os.environ)
    env.update({
        "ROUTER_PORT": str(ROUTER_PORT),
        "ROUTER_STATE": ST,
        "N_SLOTS": "1", "AUTO_CREATE_SESSIONS": "true",
        "CB_HUMAN_SLOTS": "1", "CB_AGENT_SLOTS": "0",
        "CB_HUMAN_MAX_SESSION_MIN": "240", "CB_AGENT_MAX_SESSION_MIN": "240",
        "CB_QUEUE_POLL_INTERVAL_S": "5", "CB_REAPER_INTERVAL_S": "60",
        "CB_AGENT_TOKEN": "test-token", "NEKO_PASSWORD": "neko",
        "SLOT_PORT": "18090", "FILES_PORT": "18090",
        "GRANT_ROOT": GRANTS,
        "CB_GRANTHUB_BROKER_TOKEN": BROKER,
        "CB_GRANTHUB_ADMIN_TOKEN": "x",
        "CB_OTP_AGENT_TOKEN": AGENT,
        "CB_OTP_TTL_S": "1",
        "GRANTHUB_STATUS_URL": "",
    })
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "router-bootstrap.py")], env=env,
        stdout=open("/tmp/d2-router.log", "a"), stderr=subprocess.STDOUT,
        text=True, bufsize=1)
    ok = True
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(ROUTER + "/health", timeout=2)
                break
            except Exception:
                time.sleep(0.25)
        E = "spike-user@aikumi.pro"
        req("POST", "/otp/request", email=E, token=BROKER)
        req("POST", "/otp/submit", email=E, body={"code": "999999"}, token=AGENT)
        time.sleep(2.2)
        code, j = jget("GET", "/otp/pending", email=E, token=BROKER)
        # expired → the submitted code must be gone (and ttl reported 0)
        if j.get("code") is not None:
            print("FAIL otp ttl expiry did not clear code")
            ok = False
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except Exception:
            proc.kill()
    return ok

def main():
    results = []
    results.append(("totp RFC vectors", test_totp()))
    results.append(("totp secret parsing", test_totp_secret_parsing()))
    results.append(("vault-client", test_vault_client()))
    results.append(("broker MFA decision", test_broker_mfa()))
    results.append(("router OTP endpoints", test_router_otp()))
    results.append(("router OTP TTL", test_router_otp_ttl()))
    npass = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(("PASS " if ok else "FAIL ") + name)
    print(f"D2 suite: {npass}/{len(results)}")
    return 0 if npass == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
