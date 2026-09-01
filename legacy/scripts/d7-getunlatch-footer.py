#!/usr/bin/env python3
"""D7 — Getunlatch login + CRM footer proof from a user's GrantHub grant.

Runs inside the user's assigned slot. The vault key, refresh/access tokens and
login password remain inside this process and are never printed. Output is
status/geometry only.
"""
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

sys.path.insert(0, "/etc/neko/supervisord")
sys.path.insert(0, "/etc/neko/supervisord/vendor")
import gcm  # noqa: E402
from pyaes import AESModeOfOperationCBC, Decrypter  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "sso_broker_mod", "/etc/neko/supervisord/sso-broker.py")
sb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sb)
CDP = sb.CDP
attach_page = sb.attach_page
eval_js = sb.eval_js

CDP_HTTP = "http://127.0.0.1:9222"
VAULT = "https://secrets.pmo.city"
CRM_URL = "https://alsei-residentiel.getunlatch.com/admin/re-purchases/?mode=CRM"
LOGIN_HOST = "alsei-residentiel.getunlatch.com"


def _b64d(s):
    return base64.b64decode(s)


def _decrypt(enc, key64):
    if not isinstance(enc, str) or "." not in enc:
        return enc
    parts = enc.split(".")
    if len(parts) != 2 or int(parts[0]) != 2:
        raise ValueError("unsupported encType")
    iv, ct, mac = (_b64d(x) for x in parts[1].split("|"))
    want = hmac.new(key64[32:64], iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, want):
        raise ValueError("MAC mismatch")
    dec = Decrypter(AESModeOfOperationCBC(key64[:32], iv=iv))
    pt = dec.feed(ct) + dec.feed()
    return pt.decode("utf-8")


def unwrap_grant(user):
    gdir = "/data/sessions/%s/grant" % user
    with open(os.path.join(gdir, "grant.json")) as f:
        grant = json.load(f)
    with open(os.path.join(gdir, "k_user.bin"), "rb") as f:
        k_user = f.read()

    def unwrap(w):
        return gcm.gcm_decrypt(
            k_user, base64.b64decode(w["nonce"]),
            base64.b64decode(w["ct"]), base64.b64decode(w["tag"]))

    key64 = unwrap(grant["wrapped_key"])
    rt = unwrap(grant["wrapped_session"]).decode()
    if len(key64) != 64:
        raise RuntimeError("bad user key")
    return key64, rt, grant, k_user, gdir


def mint(rt):
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": rt,
        "client_id": "web", "deviceType": "12",
        "deviceIdentifier": "d7-getunlatch", "deviceName": "cloudbrowser-broker",
    }).encode()
    req = urllib.request.Request(
        VAULT + "/identity/connect/token", method="POST", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def persist_rotated(grant, k_user, gdir, new_rt):
    iv = os.urandom(12)
    ct, tag = gcm.gcm_encrypt(k_user, iv, new_rt.encode())
    grant["wrapped_session"] = {
        "nonce": base64.b64encode(iv).decode(),
        "ct": base64.b64encode(ct).decode(),
        "tag": base64.b64encode(tag).decode(),
    }
    tmp = os.path.join(gdir, "grant.json.tmp")
    with open(tmp, "w") as f:
        json.dump(grant, f, indent=2)
    os.replace(tmp, os.path.join(gdir, "grant.json"))


def get_creds(user):
    key64, rt, grant, k_user, gdir = unwrap_grant(user)
    tok = mint(rt)
    if tok.get("refresh_token"):
        persist_rotated(grant, k_user, gdir, tok["refresh_token"])
    at = tok.get("access_token")
    if not at:
        raise RuntimeError("no access token")
    req = urllib.request.Request(
        VAULT + "/api/sync",
        headers={"Authorization": "Bearer " + at, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        sync = json.loads(r.read().decode())
    candidates = []
    for item in sync.get("ciphers") or []:
        name = item.get("name") or ""
        try:
            name = _decrypt(name, key64)
        except Exception:
            pass
        login = item.get("login") or {}
        uris = []
        for ent in login.get("uris") or []:
            uri = ent.get("uri") or ""
            try:
                uri = _decrypt(uri, key64)
            except Exception:
                pass
            uris.append(uri)
        if "getunlatch" in str(name).lower() or any("getunlatch" in str(u).lower() for u in uris):
            candidates.append((item, str(name)))
    if len(candidates) != 1:
        raise RuntimeError("getunlatch item count=%d" % len(candidates))
    item, _name = candidates[0]
    login = item.get("login") or {}
    username = _decrypt(login.get("username") or "", key64)
    password = _decrypt(login.get("password") or "", key64)
    if not username or not password:
        raise RuntimeError("item missing login fields")
    return username, password


def target_for(cdp, needle):
    r = cdp.cmd("Target.getTargets")
    return next((t for t in r.get("result", {}).get("targetInfos", [])
                 if t.get("type") == "page" and needle in (t.get("url") or "")), None)


FILL = """(() => {
 const email=document.querySelector('input[type=email],input[name=email],input[autocomplete=username]');
 if(!email) return {ok:false,phase:'email-missing'};
 const set=(el,v)=>{const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(el,v);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));};
 set(email,__U__);
 const b=[...document.querySelectorAll('button,input[type=submit]')].find(x=>/next|suivant|connexion|login/i.test(x.innerText||x.value||''));
 if(b){b.click();return {ok:true,phase:'email-submit'};} const f=email.form;if(f){f.requestSubmit();return {ok:true,phase:'email-submit'};} return {ok:false,phase:'no-email-submit'};
})()"""
PASS = """(() => {
 const p=document.querySelector('input[type=password],input[name=password]');
 if(!p) return {ok:false,phase:'password-missing'};
 const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;s.call(p,__P__);p.dispatchEvent(new Event('input',{bubbles:true}));p.dispatchEvent(new Event('change',{bubbles:true}));
 const b=[...document.querySelectorAll('button,input[type=submit]')].find(x=>/connexion|login|sign in|valider/i.test(x.innerText||x.value||''));
 if(b){b.click();return {ok:true,phase:'password-submit'};} const f=p.form;if(f){f.requestSubmit();return {ok:true,phase:'password-submit'};} return {ok:false,phase:'no-password-submit'};
})()"""

FOOTER = r"""(() => {
 const all=[...document.querySelectorAll('*')];
 const vis=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
 const rx=/(\d[\d .]*)\s*-\s*(\d[\d .]*)\s*sur\s*(\d[\d .]*)/i;
 let hit=null;
 for(const e of all){const t=(e.innerText||e.textContent||'').trim();if(t.length<100&&rx.test(t)&&vis(e)){hit=e;break;}}
 if(!hit) return {ok:false,url:location.href,title:document.title,viewport:{w:innerWidth,h:innerHeight,dpr:devicePixelRatio}};
 const r=hit.getBoundingClientRect();
 const buttons=[...document.querySelectorAll('button,[role=button]')].filter(vis).filter(e=>{const q=e.getBoundingClientRect();return Math.abs(q.top-r.top)<100;});
 return {ok:true,url:location.href,title:document.title,text:(hit.innerText||hit.textContent||'').trim().slice(0,120),rect:{x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom},viewport:{w:innerWidth,h:innerHeight,dpr:devicePixelRatio},fullyVisible:r.top>=0&&r.bottom<=innerHeight,nearbyButtons:buttons.length,zoom:devicePixelRatio};
})()"""


def main():
    user = os.environ.get("D7_USER", "")
    if not user:
        print("FAIL: D7_USER required")
        return 1
    print("grant-sync: start", flush=True)
    try:
        username, password = get_creds(user)
        print("grant-sync: usable; getunlatch item exactly one; fields decrypted", flush=True)
    except Exception as e:
        print("FAIL grant-sync:", type(e).__name__, str(e)[:120])
        return 1
    cdp = CDP(9222)
    target = target_for(cdp, LOGIN_HOST)
    if not target:
        print("FAIL: existing Getunlatch tab not found")
        return 1
    sid = attach_page(cdp, target["targetId"])
    if not sid:
        print("FAIL: attach")
        return 1
    expr = FILL.replace("__U__", json.dumps(username))
    done = False
    for _ in range(15):
        res = eval_js(cdp, sid, expr, timeout=10)
        if isinstance(res, dict) and res.get("ok"):
            print("login: email submitted", flush=True); done=True; break
        time.sleep(2)
    if not done:
        print("FAIL: email form unavailable")
        return 1
    done = False
    expr = PASS.replace("__P__", json.dumps(password))
    for _ in range(20):
        res = eval_js(cdp, sid, expr, timeout=10)
        if isinstance(res, dict) and res.get("ok"):
            print("login: password submitted", flush=True); done=True; break
        t = target_for(cdp, LOGIN_HOST)
        if t and "/admin/" in (t.get("url") or ""):
            done=True; break
        time.sleep(2)
    if not done:
        print("FAIL: password form unavailable")
        return 1
    for _ in range(40):
        t = target_for(cdp, LOGIN_HOST)
        if t and "/admin/re-purchases/" in (t.get("url") or ""):
            break
        time.sleep(2)
    else:
        t = target_for(cdp, LOGIN_HOST)
        print("FAIL: CRM not reached; url_path=%s" % urllib.parse.urlparse((t or {}).get("url", "")).path)
        return 1
    time.sleep(8)
    # Reattach after SPA/login navigation so evaluation is bound to the live document.
    sid = attach_page(cdp, t["targetId"])
    proof = eval_js(cdp, sid, FOOTER, timeout=15)
    if not isinstance(proof, dict):
        print("FAIL: footer evaluation")
        return 1
    safe = {k: proof.get(k) for k in ("ok", "title", "text", "rect", "viewport", "fullyVisible", "nearbyButtons", "zoom")}
    safe["url_path"] = urllib.parse.urlparse(proof.get("url", "")).path
    print("FOOTER_PROOF", json.dumps(safe, ensure_ascii=False), flush=True)
    return 0 if proof.get("ok") and proof.get("fullyVisible") else 2


if __name__ == "__main__":
    sys.exit(main())
