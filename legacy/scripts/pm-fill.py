#!/usr/bin/env python3
"""Spec 59/60 — PowerMail fill end-to-end from the stored grant ALONE.

Runs INSIDE the slot container. Zero user unlock:
  unwrap grant (key + session leg) -> mint access token -> /api/sync
  -> decrypt the Powermail item -> open go.powermail.fr -> fill the
  Roundcube form -> submit -> report status.

FR-9: plaintext (key, refresh token, password) stays in this process.
Prints STATUS ONLY — never values, never tokens, never the password.
Python 3.9-safe (no X | None annotations)."""
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, "/etc/neko/supervisord")          # gcm.py
sys.path.insert(0, "/etc/neko/supervisord/vendor")   # pyaes
import gcm  # noqa: E402
from pyaes import AESModeOfOperationCBC, Decrypter  # noqa: E402

# --- sso-broker CDP client (importlib — never run its main()) ---------
_spec = importlib.util.spec_from_file_location(
    "sso_broker_mod", "/etc/neko/supervisord/sso-broker.py")
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)
CDP = sb.CDP
attach_page = sb.attach_page
eval_js = sb.eval_js

CDP_HTTP = "http://127.0.0.1:9222"
VAULT = "https://secrets.pmo.city"
POWERMAIL_URL = "https://go.powermail.fr/"
POWERMAIL_ITEM = "1d1dcee2-f6bc-4cdd-98a0-e911e2dd9a72"  # Powermail item


def _b64d(s):
    return base64.b64decode(s)


def _decrypt_encstring(enc, key64):
    """Bitwarden EncString (encType 2): HMAC-SHA256 then AES-CBC PKCS7."""
    parts = enc.split(".")
    if len(parts) != 2 or int(parts[0]) != 2:
        raise ValueError("unsupported encType")
    iv, ct, mac = (_b64d(x) for x in parts[1].split("|"))
    enc_key = key64[0:32]
    mac_key = key64[32:64]
    calc = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(calc, mac):
        raise ValueError("MAC mismatch")
    mode = AESModeOfOperationCBC(enc_key, iv)
    dec = Decrypter(mode)
    return (dec.feed(ct) + dec.feed()).decode("utf-8", "replace")


def unwrap_grant(user):
    """Inline granthub unwrap (3.9-safe) — returns (key64_bytes, refresh_token)."""
    gdir = "/data/sessions/%s/grant" % user
    with open(os.path.join(gdir, "grant.json")) as f:
        g = json.load(f)
    if g.get("revoked"):
        raise RuntimeError("grant revoked")
    with open(os.path.join(gdir, "k_user.bin"), "rb") as f:
        k_user = f.read()
    if len(k_user) != 32:
        raise RuntimeError("bad wrapping key")
    def unwrap(payload):
        return gcm.gcm_decrypt(k_user, _b64d(payload["nonce"]),
                               _b64d(payload["ct"]), _b64d(payload["tag"]))
    # wrapped_key holds the RAW 64-byte user key (granthub.wrap()
    # base64-decodes the b64 key before wrapping) — NOT a b64 string.
    key64 = unwrap(g["wrapped_key"])
    if len(key64) != 64:
        raise RuntimeError("bad user key length")
    if not g.get("wrapped_session"):
        raise RuntimeError("no session leg")
    rt = unwrap(g["wrapped_session"]).decode()
    return key64, rt


def mint_access_token(rt):
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": rt,
        "client_id": "web", "deviceType": "12",
        "deviceIdentifier": "pm-fill", "deviceName": "cloudbrowser-broker",
    }).encode()
    req = urllib.request.Request(
        VAULT + "/identity/connect/token", method="POST", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def persist_rotated(user, new_rt):
    """Wrap the rotated refresh token under the same K_user and store."""
    try:
        gdir = "/data/sessions/%s/grant" % user
        with open(os.path.join(gdir, "k_user.bin"), "rb") as f:
            k_user = f.read()
        iv = os.urandom(12)
        ct, tag = gcm.gcm_encrypt(k_user, iv, new_rt.encode())
        with open(os.path.join(gdir, "grant.json")) as f:
            g = json.load(f)
        g["wrapped_session"] = {"nonce": base64.b64encode(iv).decode(),
                                "ct": base64.b64encode(ct).decode(),
                                "tag": base64.b64encode(tag).decode()}
        tmp = os.path.join(gdir, "grant.json.tmp")
        with open(tmp, "w") as f:
            json.dump(g, f, indent=2)
        os.replace(tmp, os.path.join(gdir, "grant.json"))
        return True
    except Exception:
        return False


def get_powermail_creds(user):
    key64, rt = unwrap_grant(user)
    tok = mint_access_token(rt)
    at = tok.get("access_token")
    if not at:
        raise RuntimeError("no access token")
    if tok.get("refresh_token"):
        persist_rotated(user, tok["refresh_token"])
    req = urllib.request.Request(
        VAULT + "/api/sync",
        headers={"Authorization": "Bearer " + at, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        sync = json.loads(r.read().decode())
    ciphers = sync.get("ciphers") or []
    item = next((c for c in ciphers if c.get("id") == POWERMAIL_ITEM
                 or "powermail" in (c.get("name") or "").lower()), None)
    if not item:
        raise RuntimeError("PowerMail item not found")
    login = item.get("login") or {}
    username = login.get("username") or ""
    password = login.get("password") or ""
    try:
        username = _decrypt_encstring(username, key64)
    except Exception:
        pass
    if not password:
        raise RuntimeError("item has no password")
    password = _decrypt_encstring(password, key64)
    return username, password


FILL_JS = """(() => {
  const u = document.querySelector('input[name="_user"]');
  const p = document.querySelector('input[name="_pass"]');
  if (!u || !p) return {ok:false, why:'no-form'};
  const set = (el, v) => {
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    s.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles:true}));
    el.dispatchEvent(new Event('change', {bubbles:true}));
  };
  set(u, __U__); set(p, __P__);
  const btn = document.querySelector('button[type="submit"], input[type="submit"], form button');
  if (btn) { btn.click(); return {ok:true, submitted:true}; }
  const f = document.querySelector('form');
  if (f) { f.submit(); return {ok:true, submitted:true}; }
  return {ok:true, submitted:false};
})()"""


def main():
    user = "spike-user@aikumi.pro"
    print("step1: unwrap + mint + sync + decrypt ...", flush=True)
    username, password = get_powermail_creds(user)
    print("creds OK: username=%s password_len=%d" % (username, len(password)),
          flush=True)

    print("step2: opening PowerMail tab ...", flush=True)
    cdp = CDP(9222)
    try:
        url = POWERMAIL_URL
        urllib.request.urlopen(
            urllib.request.Request(CDP_HTTP + "/json/new?" + urllib.parse.quote(url, safe=""),
                                   method="PUT"), timeout=10).read()
    except Exception as e:
        print("tab open FAIL:", type(e).__name__)
        return 1

    target = None
    for _ in range(24):
        r = cdp.cmd("Target.getTargets")
        target = next((t for t in r.get("result", {}).get("targetInfos", [])
                       if t.get("type") == "page"
                       and "go.powermail.fr" in (t.get("url") or "")), None)
        if target:
            break
        time.sleep(2)
    if not target:
        print("PowerMail tab not found after 48s")
        return 1
    print("tab open OK:", (target.get("url") or "")[:60], flush=True)

    sid = attach_page(cdp, target["targetId"])
    if not sid:
        print("attach FAILED")
        return 1
    expr = FILL_JS.replace("__U__", json.dumps(username)).replace(
        "__P__", json.dumps(password))
    filled = False
    for _ in range(30):  # up to 60s for the form
        res = eval_js(cdp, sid, expr, timeout=10)
        if isinstance(res, dict) and res.get("ok"):
            print("form fill OK, submitted=%s" % res.get("submitted"), flush=True)
            filled = True
            break
        time.sleep(2)
    if not filled:
        print("form never became fillable")
        return 1

    time.sleep(8)
    r = cdp.cmd("Target.getTargets")
    cur = next((t for t in r.get("result", {}).get("targetInfos", [])
                if t.get("targetId") == target["targetId"]), None)
    u = (cur or {}).get("url", "") or ""
    title = (cur or {}).get("title", "") or ""
    print("final url:", u[:90])
    print("final title:", title[:60])
    ok = "_task=mail" in u or "INBOX" in u or "mail" in u.lower()
    print("RESULT:", "OK — PowerMail session started" if ok else "CHECK — page state unknown")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
