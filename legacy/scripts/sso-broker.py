#!/usr/bin/env python3
"""D15 sso-broker — slot SSO/GrantHub watcher daemon.

Watches kiosk Chrome via CDP (loopback 9222) for a tab on the tinyauth/IdP
origins (auth.pmo.city / auth.aikumi.app — the SSO login redirect), then
fills the Authentik identification/MFA stages with the current owner's
Vaultwarden-sourced credentials and verifies the named TinyAuth session
cookie. Periodic session health checks proactively refresh an expiring
session by reloading one existing trusted PMO City application tab; no tab is
created or evicted. The same loop reconnects after Chrome/container restarts.

Security invariants (spec 23-d15-sso.md):
- fill only on the two whitelisted origins, never anywhere else
- credentials live in memory only; source file is 0600 + shredded after use
- logs carry events/status only — never values
- kill-switch env SSO_BROKER_ENABLED=false

Fleet slot variant (D3.1, spec 47 GH.4): same daemon, one more watcher —
GrantHub capture. When a tab on the vault host (secrets.pmo.city) is seen
and the vault unlocks (the USER logs in with their master password — never
the broker), the broker reads the in-memory user key via the vault app's
own keyService (proven in the W1 spike, 2026-08-22), POSTs it to the
GrantHub API (router /connect/grant, internal + shared broker token,
Remote-Email = slot owner), where it is AES-GCM-wrapped with a per-user
K_user. The plaintext key never leaves the slot except over the internal
API call and is never logged. Active only when SLOT_USER_FILE exists (the
reference viewer has none → capture dormant).
"""
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

import totp  # noqa: E402  (spec 73 — RFC 6238, same scripts volume)

CDP_HTTP = os.environ.get("SSO_CDP", "http://127.0.0.1:9222")
CREDS_FILE = os.environ.get("SSO_CREDS_FILE", "/etc/neko/supervisord/sso-creds.b64")
AUTH_HOSTS = ("auth.pmo.city", "auth.aikumi.app")
POLL_S = float(os.environ.get("SSO_POLL_S", "2"))
LOGIN_TIMEOUT_S = float(os.environ.get("SSO_LOGIN_TIMEOUT_S", "25"))
SESSION_DOMAIN = ".pmo.city"
# TinyAuth v5 derives this exact name as:
# tinyauth-session- + first 8 chars of UUIDv5(URL namespace, auth.pmo.city).
# Keep it explicit so a prefix collision or host-only lookalike can never be
# mistaken for the PMO City authentication session.
SESSION_COOKIE_NAME = os.environ.get(
    "SSO_SESSION_COOKIE_NAME", "tinyauth-session-39fcd0f6").strip()
SESSION_CHECK_S = max(10.0, float(os.environ.get("SSO_SESSION_CHECK_S", "300")))
SESSION_RELOGIN_BEFORE_S = max(
    60.0, float(os.environ.get("SSO_SESSION_RELOGIN_BEFORE_S", "900")))
SESSION_RELOGIN_COOLDOWN_S = max(
    30.0, float(os.environ.get("SSO_SESSION_RELOGIN_COOLDOWN_S", "120")))
SESSION_PROBE_ORIGINS = tuple(
    x.strip().rstrip("/") for x in os.environ.get(
        "SSO_SESSION_PROBE_ORIGINS",
        "https://pmo.city,https://cloudbrowser.dev01.pmo.city,"
        "https://cloudfiles.dev01.pmo.city",
    ).split(",") if x.strip()
)


def _canonical_session_cookie(cookie):
    """True only for the one exact, security-scoped TinyAuth cookie."""
    return (
        (cookie.get("name") or "") == SESSION_COOKIE_NAME
        and (cookie.get("domain") or "").lower() == SESSION_DOMAIN
        and (cookie.get("path") or "") == "/"
        and cookie.get("secure") is True
        and cookie.get("httpOnly") is True
    )

# --- GrantHub capture (spec 47 GH.4) ------------------------------------
# The router is reachable from the slot containers on the compose default
# network by service name. GRANTHUB_URL is the internal grant endpoint;
# GRANTHUB_STATUS_URL is the internal status endpoint (checks whether a
# grant already exists before re-capturing).
GRANTHUB_URL = os.environ.get("GRANTHUB_URL",
                              "http://router:8081/connect/grant")
GRANTHUB_STATUS_URL = os.environ.get("GRANTHUB_STATUS_URL",
                                     "http://router:8081/connect/status")
# Audit B3/B4 (spec 66 isolation): each slot uses its OWN broker bearer
# (CB_SLOT_<n>_TOKEN — Coolify magic var SERVICE_PASSWORD_64_SLOT<n>BROKER).
# The router derives the slot from the bearer and binds every operation to
# the slot's current owner. Fallback to the legacy shared token only when
# no per-slot token is configured.
CB_SLOT_N = int(os.environ.get("CB_SLOT_N", "0") or 0)
CB_SLOT_TOKEN = os.environ.get(f"CB_SLOT_{CB_SLOT_N}_TOKEN", "") if CB_SLOT_N else ""
CB_GRANTHUB_BROKER_TOKEN = os.environ.get("CB_GRANTHUB_BROKER_TOKEN", "")
BROKER_TOKEN = CB_SLOT_TOKEN or CB_GRANTHUB_BROKER_TOKEN

# The slot env's GRANTHUB_URL is the PUBLIC /connect page (top-bar pill
# navigation). The broker must never POST the key there (tinyauth would
# 401 it). Use an explicit GRANTHUB_POST_URL when set, else accept
# GRANTHUB_URL only if it already points at the /connect/grant endpoint,
# otherwise fall back to the internal router service name.
GRANTHUB_POST_URL = os.environ.get("GRANTHUB_POST_URL", "")
if not GRANTHUB_POST_URL:
    if GRANTHUB_URL.rstrip("/").endswith("/grant"):
        GRANTHUB_POST_URL = GRANTHUB_URL
    else:
        GRANTHUB_POST_URL = "http://router:8081/connect/grant"
VAULT_HOST = os.environ.get("VAULT_HOST", "secrets.pmo.city")
SLOT_USER_FILE = os.environ.get("SLOT_USER_FILE",
                                "/home/neko/Downloads/.slot-user.json")
VAULT_POLL_S = float(os.environ.get("VAULT_POLL_S", "2"))
VAULT_KEY_TIMEOUT_S = float(os.environ.get("VAULT_KEY_TIMEOUT_S", "120"))
GRANT_SCOPE = os.environ.get("GRANT_SCOPE", "PMO City vault")

# --- Spec 73 (D2) — MFA code-exchange (chat-ask leg) ----------------------
# The code is exchanged through the ROUTER's in-memory OTP endpoints
# (never persisted, never logged): the broker POSTs a request, the agent
# submits the user's code, the broker fetches it ONCE. The seed path is
# fully local (totp module) — no network round trip.
OTP_REQUEST_URL = os.environ.get("OTP_REQUEST_URL",
                                 "http://router:8081/otp/request")
OTP_PENDING_URL = os.environ.get("OTP_PENDING_URL",
                                 "http://router:8081/otp/pending")
MFA_TIMEOUT_S = float(os.environ.get("SSO_MFA_TIMEOUT_S", "120"))
SSO_VAULT_ITEM = os.environ.get("SSO_VAULT_ITEM", "Authentik Spike User")
SSO_VAULT_ITEM_ID = os.environ.get("SSO_VAULT_ITEM_ID", "")
# Overridable scripts dir (local tests) for the lazy vault-client import.
SLOT_SCRIPTS_DIR = os.environ.get("CB_SLOT_SCRIPTS",
                                  "/etc/neko/supervisord")

# Reads the vault app's in-memory user key (bitwardenContainerService —
# the web vault 2026.x container). Tries the active user first, then the
# per-user localStorage prefix (user_<uuid>_), then the profile API.
# getUserKey() returns a Promise in 2026.x — the expression is async and
# eval_js runs it with awaitPromise. Returns {ok, uid?, key?} — never
# logged by the broker.
KEY_JS = """(async () => {
  const b = window.bitwardenContainerService;
  if (!b || !b.keyService) return {ok:false, why:'no-container'};
  const ks = b.keyService;
  let uid = null;
  try {
    uid = (b.stateService && b.stateService.activeUserId$ &&
           b.stateService.activeUserId$.value) || null;
  } catch (e) {}
  if (!uid) {
    try {
      const re = /^user_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_/;
      for (let i = 0; i < localStorage.length; i++) {
        const m = localStorage.key(i).match(re);
        if (m) { uid = m[1]; break; }
      }
    } catch (e) {}
  }
  if (!uid) return {ok:false, why:'no-user'};
  let k = null;
  try { k = await ks.getUserKey(uid); } catch (e) {}
  if (!k) return {ok:false, why:'locked'};
  let b64 = null;
  try { b64 = k.toBase64(); } catch (e) {}
  if (!b64 || b64.length < 80) return {ok:false, why:'bad-key'};
  return {ok:true, uid: uid, key: b64};
})()"""

# Spec 59 — session-token leg. The Bitwarden web vault keeps its API
# tokens in the SDK's in-memory stateService, which is NOT exposed on
# window.bitwardenContainerService (probed 2026-08-25: only
# encryptService + keyService). Deterministic alternative: the SSO
# round-trip the broker itself drives ends with the vault SPA POSTing
# /identity/connect/token (grant_type=authorization_code); the response
# body carries refresh_token. HOOK_JS wraps fetch/XHR on the vault
# origin and copies that refresh token into a window global; the broker
# installs it via Page.addScriptToEvaluateOnNewDocument (survives the
# auth redirect navigations) + once on the current document. The value
# is read once by the broker (COLLECT_JS), wrapped, and NEVER logged.
HOOK_JS = r"""(() => {
  if (window.__cb_hooked) return;
  window.__cb_hooked = true;
  window.__cb_refresh_token = null;
  const grab = (body) => {
    try {
      const j = JSON.parse(body);
      if (j && typeof j.refresh_token === 'string' && j.refresh_token.length > 20) {
        window.__cb_refresh_token = j.refresh_token;
      }
    } catch (e) {}
  };
  const of = window.fetch;
  if (of) window.fetch = function(...args) {
    return of.apply(this, args).then((r) => {
      try {
        const a0 = args[0];
        const u = (typeof a0 === 'string') ? a0 : (a0 && (a0.url || a0.input));
        if (u && String(u).indexOf('/identity/connect/token') !== -1) {
          r.clone().text().then(grab).catch(() => {});
        }
      } catch (e) {}
      return r;
    });
  };
  const oOpen = XMLHttpRequest.prototype.open;
  const oSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m, u) { this.__cb_url = u; return oOpen.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(...a) {
    try {
      this.addEventListener('load', () => {
        try {
          if (this.__cb_url && String(this.__cb_url).indexOf('/identity/connect/token') !== -1) {
            grab(this.responseText);
          }
        } catch (e) {}
      });
    } catch (e) {}
    return oSend.apply(this, arguments);
  };
})()"""

COLLECT_JS = """(() => {
  const v = window.__cb_refresh_token || null;
  window.__cb_refresh_token = null;
  return v;
})()"""

# --- Spec 73 (D2) — Authentik MFA stage (TOTP code) -----------------------
# Authentik 2025.8.1 exact nesting:
# executor.shadowRoot -> ak-stage-authenticator-validate.shadowRoot ->
# ak-stage-authenticator-validate-code.shadowRoot. The code component is
# shared by Static/TOTP/Email/SMS, so autonomous fill is allowed only when
# deviceChallenge.deviceClass is exactly "totp".
TOTP_PROBE_JS = """(() => {
  const fe = document.querySelector('ak-flow-executor');
  if (!fe || !fe.shadowRoot) return {ok:false, why:'no-executor'};
  const validate = fe.shadowRoot.querySelector('ak-stage-authenticator-validate');
  if (!validate || !validate.shadowRoot) return {ok:false, why:'no-validate'};
  const codeStage = validate.shadowRoot.querySelector('ak-stage-authenticator-validate-code');
  if (codeStage) {
    const sr = codeStage.shadowRoot || codeStage;
    const dc = codeStage.deviceChallenge && codeStage.deviceChallenge.deviceClass;
    if (dc !== 'totp') return {ok:false, why:'wrong-device-class', deviceClass:dc || null};
    return {ok:true, present: !!sr.querySelector('input[name="code"]'), deviceClass:'totp'};
  }
  const challenges = (validate.challenge && validate.challenge.deviceChallenges) || [];
  return {ok:true, picker: challenges.some(c => c && c.deviceClass === 'totp')};
})()"""

TOTP_FILL_JS = """(() => {
  const fe = document.querySelector('ak-flow-executor');
  if (!fe || !fe.shadowRoot) return {ok:false, why:'no-executor'};
  const validate = fe.shadowRoot.querySelector('ak-stage-authenticator-validate');
  if (!validate || !validate.shadowRoot) return {ok:false, why:'no-validate'};
  const st = validate.shadowRoot.querySelector('ak-stage-authenticator-validate-code');
  if (!st) return {ok:false, why:'no-code-stage'};
  const dc = st.deviceChallenge && st.deviceChallenge.deviceClass;
  if (dc !== 'totp') return {ok:false, why:'wrong-device-class', deviceClass:dc || null};
  const sr = st.shadowRoot || st;
  const inp = sr.querySelector('input[name="code"]');
  if (!inp) return {ok:false, why:'no-code-input'};
  const setVal = (el, v) => {
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    s.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles:true, composed:true}));
    el.dispatchEvent(new Event('change', {bubbles:true, composed:true}));
  };
  if (inp.value !== __CODE__) setVal(inp, __CODE__);
  // 2026.x uses button[name="continue"]; 2025.8.x a plain type=submit —
  // accept both, then fall back to the form's native submit.
  const btn = sr.querySelector('button[name="continue"]')
              || sr.querySelector('button[type="submit"]');
  if (btn) { btn.click(); return {ok:true, submitted:true}; }
  const f = sr.querySelector('form');
  if (f) { if (f.requestSubmit) f.requestSubmit(); else f.submit(); return {ok:true, submitted:true}; }
  return {ok:true, submitted:false};
})()"""

TOTP_PICK_JS = """(() => {
  const fe = document.querySelector('ak-flow-executor');
  if (!fe || !fe.shadowRoot) return {ok:false, why:'no-executor'};
  const st = fe.shadowRoot.querySelector('ak-stage-authenticator-validate');
  if (!st || !st.shadowRoot) return {ok:false, why:'no-validate'};
  const challenges = (st.challenge && st.challenge.deviceChallenges) || [];
  const index = challenges.findIndex(c => c && c.deviceClass === 'totp');
  if (index < 0) return {ok:false, why:'no-totp-device'};
  const buttons = st.shadowRoot.querySelectorAll('button.authenticator-button');
  if (!buttons[index]) return {ok:false, why:'totp-button-missing'};
  buttons[index].click();
  return {ok:true, clicked:true, deviceClass:'totp'};
})()"""

if os.environ.get("SSO_BROKER_ENABLED", "true").lower() == "false":
    print("[sso-broker] disabled via SSO_BROKER_ENABLED=false — exiting")
    sys.exit(0)


def log(msg):
    print(f"[sso-broker] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


# ---------- minimal RFC6455 CDP client (proven in W1 e2e) ----------
class CDP:
    def __init__(self, port):
        self.port = port
        ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5))
        self.browser = ver.get("Browser")
        self.sock = self._connect(ver["webSocketDebuggerUrl"])
        self.msg_id = 0

    def _connect(self, ws_url):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        sock.settimeout(10)  # belt-and-braces: never block past the timeout
        key = base64.b64encode(os.urandom(16)).decode()
        path = "/" + ws_url.split("/", 3)[3]
        req = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += sock.recv(4096)
        if b" 101 " not in resp.split(b"\r\n")[0]:
            raise RuntimeError(f"ws handshake failed: {resp[:100]}")
        return sock

    def send(self, obj):
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header = bytes([0x81, 0x80 | n])
        elif n < 65536:
            header = bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big")
        else:
            header = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big")
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def recv(self, timeout=15):
        self.sock.settimeout(timeout)
        buf = b""
        while True:
            h = self.sock.recv(2)
            if len(h) < 2:
                return None
            opcode = h[0] & 0x0F
            ln = h[1] & 0x7F
            if ln == 126:
                ln = int.from_bytes(self.sock.recv(2), "big")
            elif ln == 127:
                ln = int.from_bytes(self.sock.recv(8), "big")
            payload = b""
            while len(payload) < ln:
                chunk = self.sock.recv(ln - len(payload))
                if not chunk:
                    break
                payload += chunk
            if opcode == 1:
                return json.loads(payload.decode())
            if opcode == 8:
                return None
            buf += payload

    def cmd(self, method, params=None, session=None, timeout=15):
        self.msg_id += 1
        msg = {"id": self.msg_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.send(msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = self.recv(timeout=deadline - time.time())
            if r is None:
                break
            if r.get("id") == self.msg_id:
                return r
        raise TimeoutError(f"no reply for {method}")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def attach_page(cdp, target_id):
    """Attach flatten:true — sessionId arrives in the attachedToTarget EVENT."""
    cdp.msg_id += 1
    cdp.send({"id": cdp.msg_id, "method": "Target.attachToTarget",
              "params": {"targetId": target_id, "flatten": True}})
    deadline = time.time() + 10
    while time.time() < deadline:
        r = cdp.recv(timeout=deadline - time.time())
        if r is None:
            break
        if r.get("method") == "Target.attachedToTarget":
            return r["params"].get("sessionId")
    return None


FILL_JS = """(() => {
  const fe = document.querySelector('ak-flow-executor');
  if (!fe || !fe.shadowRoot) return {ok:false, why:'no-executor'};
  const st = fe.shadowRoot.querySelector('ak-stage-identification');
  if (!st || !st.shadowRoot) return {ok:false, why:'no-stage'};
  const sr = st.shadowRoot;
  const uid = sr.querySelector('input[name=uidField]');
  // 2025.8.1 ak-flow-input-password renders in light DOM.
  const pwdHost = sr.querySelector('ak-flow-input-password');
  const pwd = pwdHost && pwdHost.querySelector('input[name=password]');
  if (!uid || !pwd) return {ok:false, why:'no-fields'};
  const setVal = (el, v) => {
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    s.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles:true, composed:true}));
    el.dispatchEvent(new Event('change', {bubbles:true, composed:true}));
  };
  if (!uid.value) setVal(uid, __U__);
  if (!pwd.value) setVal(pwd, __P__);
  const btn = sr.querySelector('button[type=submit]');
  if (btn) { btn.click(); return {ok:true, submitted:true}; }
  return {ok:true, submitted:false};
})()"""


def eval_js(cdp, session, expr, timeout=12):
    r = cdp.cmd("Runtime.evaluate",
                {"expression": expr, "returnByValue": True,
                 "awaitPromise": True},
                session=session, timeout=timeout)
    if "error" in r:
        return None
    res = r.get("result", {})
    if "exceptionDetails" in res:
        return None
    return res.get("result", {}).get("value")


def is_auth_url(url):
    if not url:
        return False
    try:
        p = urllib.parse.urlsplit(url)
        return (p.scheme == "https" and p.hostname in AUTH_HOSTS
                and p.port in (None, 443)
                and p.username is None and p.password is None)
    except (TypeError, ValueError):
        return False


def find_login_target(cdp):
    r = cdp.cmd("Target.getTargets")
    for t in r.get("result", {}).get("targetInfos", []):
        if t.get("type") == "page" and is_auth_url(t.get("url", "")):
            return t
    return None


def fill_and_submit(cdp, target):
    """Fill + submit the Authentik identification stage. Returns True if the
    tab left the auth origins within the timeout."""
    session = attach_page(cdp, target["targetId"])
    if session is None:
        log("attach FAILED")
        return False
    # The Authentik SPA renders ak-flow-executor/ak-stage-identification
    # asynchronously — poll until the stage is fillable (or timeout).
    expr = FILL_JS.replace("__U__", json.dumps(username)).replace("__P__", json.dumps(password))
    fill_deadline = time.time() + 20
    submitted = False
    while time.time() < fill_deadline:
        res = eval_js(cdp, session, expr)
        if res and res.get("ok"):
            if res.get("submitted"):
                submitted = True
                break
            time.sleep(1.5)
            continue
        why = res.get("why") if res else "eval-err"
        if why != "no-stage" and why != "no-executor":
            log(f"fill problem: {why}")
        time.sleep(1.5)
    if not submitted:
        log("fill not ready after 20s (stage never became submittable)")
        return False
    log("filled + submitted")
    deadline = time.time() + LOGIN_TIMEOUT_S
    while time.time() < deadline:
        time.sleep(2)
        r = cdp.cmd("Target.getTargets")
        cur = next((t for t in r.get("result", {}).get("targetInfos", [])
                    if t.get("targetId") == target["targetId"]), None)
        if cur is None:
            # tab closed mid-login: inconclusive, NOT success — keep waiting
            continue
        if not is_auth_url(cur.get("url", "")):
            log("login ok — tab left auth origins")
            return True
    return False


def _cookie_result(cdp, session=None):
    """Read cookies and reject CDP protocol/malformed responses.

    Network.getAllCookies is a page-session command in Chrome 128.  When no
    session is supplied, use the browser-level Storage domain instead; this
    keeps health/pre-login reads valid without creating or evicting a tab.
    """
    method = "Network.getAllCookies" if session else "Storage.getCookies"
    r = cdp.cmd(method, session=session) if session else cdp.cmd(method)
    if not isinstance(r, dict) or "error" in r:
        raise RuntimeError("cdp-cookie-error")
    result = r.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("cookies"), list):
        raise RuntimeError("cdp-cookie-malformed")
    return result["cookies"]


def _session_cookie_fingerprint(cookie):
    """Internal opaque identity; never log or persist cookie values."""
    if not cookie:
        return None
    return (cookie.get("name"), cookie.get("domain"), cookie.get("path"),
            cookie.get("value"))


def fresh_cookie_issued(before, after):
    return bool(after and _canonical_session_cookie(after)
                and (before is None or _session_cookie_fingerprint(before)
                     != _session_cookie_fingerprint(after)))


def _exact_session_cookie(cdp, session=None):
    hits = [c for c in _cookie_result(cdp, session=session)
            if _canonical_session_cookie(c)]
    if len(hits) > 1:
        raise RuntimeError("multiple-exact-tinyauth-cookies")
    return hits[0] if hits else None


def session_identity_matches(payload, owner):
    """Validate TinyAuth's authenticated identity against the slot owner."""
    try:
        auth = payload["auth"]
        return (int(payload.get("status")) == 200
                and auth.get("authenticated") is True
                and (auth.get("email") or "").strip().lower()
                == (owner or "").strip().lower())
    except (KeyError, TypeError, ValueError):
        return False


def probe_session_identity(cookie, session=None):
    """Ask TinyAuth to validate the opaque cookie; never log its value."""
    if not cookie or not _canonical_session_cookie(cookie) or not cookie.get("value"):
        return None
    req = urllib.request.Request(
        "https://auth.pmo.city/api/context/user",
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie['value']}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except Exception:
        return None


def validate_session_after_login(cdp, owner, before_cookie):
    """Require a fresh exact cookie whose server-side identity is the owner."""
    try:
        after = _exact_session_cookie(cdp)
    except Exception as e:
        log(f"post-login cookie validation error: {type(e).__name__}")
        return False
    if not fresh_cookie_issued(before_cookie, after):
        log("post-login cookie was not freshly issued")
        return False
    if not session_identity_matches(probe_session_identity(after), owner):
        log("post-login TinyAuth identity does not match slot owner")
        return False
    h = session_cookie_health(cdp)
    return h["valid"]


def reset_session_state(state, generation):
    """Reset D15 scheduling on every canonical assignment generation."""
    state.update({"last_session_check": 0.0,
                  "last_session_status": None,
                  "last_relogin_request": 0.0,
                  "session_generation": generation,
                  "owner_refresh_required": bool(generation)})


def session_cookie_health(cdp, now=None, session=None):
    """Return exact TinyAuth cookie validity and refresh policy separately."""
    now = time.time() if now is None else float(now)
    try:
        cookies = _cookie_result(cdp, session=session)
    except Exception as e:
        return {"healthy": False, "valid": False, "refresh_needed": False,
                "relogin": False, "status": "error",
                "reason": type(e).__name__, "ttl_s": None, "cookie": None}
    hits = [c for c in cookies if _canonical_session_cookie(c)]
    if not hits:
        return {"healthy": False, "valid": False, "refresh_needed": True,
                "relogin": True, "status": "missing",
                "reason": "no-exact-tinyauth-cookie", "ttl_s": None,
                "cookie": None}
    if len(hits) != 1:
        return {"healthy": False, "valid": False, "refresh_needed": False,
                "relogin": False, "status": "ambiguous",
                "reason": "multiple-exact-tinyauth-cookies", "ttl_s": None,
                "cookie": None}
    hit = hits[0]
    try:
        exp = float(hit.get("expires") or 0)
    except (TypeError, ValueError):
        exp = 0
    if exp <= 0:
        return {"healthy": False, "valid": False, "refresh_needed": True,
                "relogin": True, "status": "session-only",
                "reason": "no-persistent-expiry", "ttl_s": None,
                "cookie": hit}
    ttl = exp - now
    if ttl <= 0:
        return {"healthy": False, "valid": False, "refresh_needed": True,
                "relogin": True, "status": "expired",
                "reason": "expired", "ttl_s": ttl, "cookie": hit}
    if ttl <= SESSION_RELOGIN_BEFORE_S:
        return {"healthy": True, "valid": True, "refresh_needed": True,
                "relogin": True, "status": "expiring",
                "reason": "proactive-window", "ttl_s": ttl, "cookie": hit}
    return {"healthy": True, "valid": True, "refresh_needed": False,
            "relogin": False, "status": "healthy", "reason": "ok",
            "ttl_s": ttl, "cookie": hit}


def check_session_cookie(cdp):
    h = session_cookie_health(cdp)
    if h["status"] == "error":
        log(f"session cookie check error: {h['reason']}")
        return False
    ttl = h.get("ttl_s")
    suffix = f", ttl={int(ttl)}s" if isinstance(ttl, (int, float)) else ""
    log(f"session health: {h['status']}{suffix}")
    return h["valid"]


def is_session_probe_url(url):
    """Only explicitly configured PMO City application origins are trusted."""
    try:
        p = urllib.parse.urlsplit(url or "")
        if p.username is not None or p.password is not None:
            return False
        origin = f"{p.scheme.lower()}://{(p.hostname or '').lower()}"
        if p.port is not None:
            origin += f":{p.port}"
        return p.scheme.lower() == "https" and origin in SESSION_PROBE_ORIGINS
    except (TypeError, ValueError):
        return False


def find_session_probe_target(targets):
    for t in targets:
        if t.get("type") == "page" and is_session_probe_url(t.get("url", "")):
            return t
    return None


def request_session_relogin(cdp, target):
    """Expire TinyAuth auth and reload one existing trusted application tab.

    No tab is created or evicted. Deleting only the named TinyAuth cookie is
    what makes a still-valid but near-expiry session perform a fresh SSO
    round-trip; a plain reload would continue using the old cookie. The
    broker still types only on AUTH_HOSTS.
    """
    if not target or not is_session_probe_url(target.get("url", "")):
        return False
    try:
        # Prove attachment/reload capability before revoking authentication.
        sid = attach_page(cdp, target.get("targetId"))
        if not sid:
            return False
        cookies = _cookie_result(cdp, session=sid)
        hits = [c for c in cookies if _canonical_session_cookie(c)]
        if len(hits) > 1:
            return False
        if hits:
            params = {"name": SESSION_COOKIE_NAME,
                      "domain": SESSION_DOMAIN, "path": "/"}
            deleted = cdp.cmd("Network.deleteCookies", params, session=sid)
            if not isinstance(deleted, dict) or "error" in deleted:
                return False
        reloaded = cdp.cmd("Page.reload", {"ignoreCache": True},
                           session=sid, timeout=10)
        return isinstance(reloaded, dict) and "error" not in reloaded
    except Exception:
        return False


# ---------- GrantHub capture helpers (spec 47 GH.4) ----------
def marker_snapshot():
    """Return canonical immutable slot generation (user, slot, ts).

    The marker schema is owned by restart-api. Any legacy/noncanonical marker
    fails closed; owner changes are detected even if the same email is reused.
    """
    try:
        with open(SLOT_USER_FILE) as f:
            marker = json.load(f)
        user = (marker.get("user") or "").strip().lower()
        slot = int(marker.get("slot"))
        ts = float(marker.get("ts"))
        if not user or slot < 1 or ts <= 0:
            return None
        return (user, slot, ts)
    except Exception:
        return None


def slot_owner():
    snap = marker_snapshot()
    return snap[0] if snap else None


def grant_status(owner):
    """Return the /connect/status dict for the owner ({} when
    unreachable). Spec 59: 'usable' (key + session leg) is the only state
    that means fully shared."""
    status_url = GRANTHUB_STATUS_URL
    if status_url and not status_url.startswith(("http://", "https://")):
        # Browser-facing env value (same-domain path); resolve against the
        # router service for the server-side call.
        status_url = "http://router:8081" + status_url
    try:
        req = urllib.request.Request(status_url,
                                     headers={"Remote-Email": owner,
                                              "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode()) or {}
    except Exception:
        return {}  # unreachable → try to capture anyway (router will say)


def post_grant(owner, key_b64, session=None):
    """POST the captured user key (+ optional session-token leg, spec 59)
    to the GrantHub API (internal router). Returns True on 200 + usable.
    The key/token are never logged. Audit B3/B4: authenticated with the
    slot's OWN per-slot bearer (CB_SLOT_<n>_TOKEN); the router binds the
    owner server-side."""
    if not BROKER_TOKEN:
        log("ERROR: broker token unset — grant disabled")
        return False
    body = {"key": key_b64, "scope": GRANT_SCOPE}
    if session:
        body["session"] = session
    req = urllib.request.Request(
        GRANTHUB_POST_URL, method="POST",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Remote-Email": owner,
                 "Authorization": f"Bearer {BROKER_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            obj = json.loads(r.read().decode() or "{}")
            ok = r.status == 200 and bool(obj.get("usable")
                                          if session else obj.get("shared"))
            log("grant POST " + ("OK" if ok else f"refused ({r.status})")
                + (" (key+session)" if session else " (key only)"))
            return ok
    except Exception as e:
        log(f"grant POST failed: {type(e).__name__}")
        return False


def post_session(owner, refresh_token):
    """Spec 59: session-only upgrade — POST the captured refresh token to
    an EXISTING key grant (no key re-capture needed). Returns True on
    200 + usable. The token is never logged. Per-slot bearer (audit B4)."""
    if not BROKER_TOKEN:
        log("ERROR: broker token unset — session upgrade disabled")
        return False
    body = json.dumps({"session": refresh_token}).encode()
    req = urllib.request.Request(
        GRANTHUB_POST_URL, method="POST", data=body,
        headers={"Content-Type": "application/json",
                 "Remote-Email": owner,
                 "Authorization": f"Bearer {BROKER_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            obj = json.loads(r.read().decode() or "{}")
            ok = r.status == 200 and bool(obj.get("usable"))
            log("session upgrade POST " + ("OK — grant usable" if ok
                                           else f"refused ({r.status})"))
            return ok
    except Exception as e:
        log(f"session upgrade POST failed: {type(e).__name__}")
        return False


# ---------- Spec 73 (D2) — MFA code-exchange client ----------
def request_code(owner):
    """Ask the router to arm a pending OTP challenge for the owner (the
    agent then submits the user's code via /otp/submit). Returns the
    opaque challenge request id (str) or None on failure. Status-only.
    Audit B10: the id binds the exchange to THIS slot/owner/target."""
    if not BROKER_TOKEN:
        log("ERROR: broker token unset — code request disabled")
        return None
    req = urllib.request.Request(
        OTP_REQUEST_URL, method="POST", data=b"{}",
        headers={"Content-Type": "application/json",
                 "Remote-Email": owner,
                 "Authorization": f"Bearer {BROKER_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            obj = json.loads(r.read().decode() or "{}")
            rid = obj.get("request_id")
            ok = r.status == 200 and bool(obj.get("ok")) and isinstance(rid, str)
            log("mfa: code request " + ("sent" if ok else f"refused ({r.status})"))
            return rid if ok else None
    except Exception as e:
        log(f"mfa: code request failed: {type(e).__name__}")
        return None


def fetch_code(owner, challenge):
    """Read-once fetch of the submitted code for the given challenge id
    (None when not submitted/consumed). The code is NEVER logged.
    Audit B10: the challenge id binds the fetch to this slot/owner."""
    if not challenge:
        return None
    req = urllib.request.Request(
        OTP_PENDING_URL + "?challenge=" + urllib.parse.quote(challenge),
        headers={"Remote-Email": owner,
                 "Authorization": f"Bearer {BROKER_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            obj = json.loads(r.read().decode() or "{}")
            c = obj.get("code")
            return c if isinstance(c, str) and c else None
    except Exception:
        return None


def mfa_autonomous(seed):
    """Hybrid decision (FR-5 Q3): a stored seed → autonomous; no seed →
    chat-ask. Never autonomous without the stored secret."""
    return bool(seed)


def _pick_totp(cdp, session):
    try:
        eval_js(cdp, session, TOTP_PICK_JS, timeout=10)
    except Exception:
        pass


def fill_code(cdp, session, code):
    """Fill + submit the Authentik code stage. Returns True when the
    submit button was clicked (server verdict is checked by the caller
    via the tab's URL). The code exists only in this frame's JS."""
    expr = TOTP_FILL_JS.replace("__CODE__", json.dumps(code))
    for _ in range(10):
        res = eval_js(cdp, session, expr)
        if isinstance(res, dict) and res.get("ok"):
            return bool(res.get("submitted"))
        time.sleep(1.5)
    return False


def handle_mfa(cdp, target, owner, seed, heartbeat,
               generation=None, revalidate=None):
    """After identification submit: drive the Authentik TOTP stage.

    Returns:
      'ok'      — tab left the auth origins (login complete)
      'waiting' — no seed + no code arrived in time, or code rejected:
                  the HUMAN may finish the login in the kiosk (never a
                  hard block, never a guessed code)

    Autonomous leg: seed present → compute + fill (retry once with a
    fresh code on rejection), then chat-ask on repeated failure.
    Chat-ask leg: POST /otp/request → poll /otp/pending until the agent
    submits the user's code → fill once (one re-request on rejection).
    Bounded by MFA_TIMEOUT_S; heartbeat is touched every pass so the
    spec-55 watchdog never kills a legitimate wait."""
    session = attach_page(cdp, target["targetId"])
    if session is None:
        log("mfa: attach failed")
        return "failed"
    deadline = time.time() + MFA_TIMEOUT_S
    picked = False
    attempts = 0
    chat_requested = False
    challenge = None
    while time.time() < deadline:
        heartbeat[0] = time.time()
        if revalidate is not None and not revalidate():
            log("mfa: owner/generation changed — cancelling")
            return "cancel"
        r = cdp.cmd("Target.getTargets")
        cur = next((t for t in r.get("result", {}).get("targetInfos", [])
                    if t.get("targetId") == target["targetId"]), None)
        if cur is None or not is_auth_url(cur.get("url", "")):
            return "ok"
        probe = eval_js(cdp, session, TOTP_PROBE_JS)
        if isinstance(probe, dict) and probe.get("present"):
            if seed and attempts < 2:
                code = totp.totp(seed)
                if revalidate is not None and not revalidate():
                    return "cancel"
                ok = fill_code(cdp, session, code)
                attempts += 1
                log("mfa: autonomous code " + ("submitted" if ok
                                               else "fill failed"))
                time.sleep(3)
                continue
            if not chat_requested:
                # Audit B10: one-shot challenge-bound exchange — the
                # request id returned here is used for the single fetch
                # and any re-request.
                challenge = request_code(owner)
                if not challenge:
                    return "waiting"
                chat_requested = True
                log("mfa: no usable seed — code requested from agent")
            code = fetch_code(owner, challenge)
            if code:
                if revalidate is not None and not revalidate():
                    return "cancel"
                ok = fill_code(cdp, session, code)
                log("mfa: user code " + ("submitted" if ok
                                         else "fill failed"))
                attempts += 1
                chat_requested = False  # allow one re-request on rejection
                challenge = None
                time.sleep(6)
                continue
            time.sleep(2)
            continue
        if isinstance(probe, dict) and probe.get("picker") and not picked:
            picked = True
            _pick_totp(cdp, session)
            time.sleep(2)
            continue
        time.sleep(2)
    log("mfa: timeout — waiting for human to finish login")
    return "waiting"


def find_vault_target(cdp):
    """First target whose URL host is the vault (secrets.pmo.city)."""
    try:
        r = cdp.cmd("Target.getTargets")
        for t in r.get("result", {}).get("targetInfos", []):
            host = (t.get("url") or "").split("/")[2].split(":")[0].lower()
            if host == VAULT_HOST:
                return t
    except Exception:
        pass
    return None


def install_token_hook(cdp, session):
    """Spec 59: arm the refresh-token capture on the vault target.
    Page.addScriptToEvaluateOnNewDocument survives the SSO redirect
    navigations; the immediate evaluate covers the current document.
    Returns True when at least the immediate install succeeded."""
    try:
        cdp.cmd("Page.enable", session=session, timeout=10)
        cdp.cmd("Page.addScriptToEvaluateOnNewDocument",
                {"source": HOOK_JS}, session=session, timeout=10)
        eval_js(cdp, session, HOOK_JS, timeout=10)
        return True
    except Exception as e:
        log(f"token hook install failed: {type(e).__name__}")
        return False


def collect_refresh_token(cdp, session):
    """Read + clear the captured refresh token (or None). Never logged."""
    try:
        v = eval_js(cdp, session, COLLECT_JS, timeout=10)
        return v if isinstance(v, str) and v else None
    except Exception:
        return None


def capture_vault_key(cdp, target, owner):
    """Attach to the vault tab, arm the token hook, poll KEY_JS until the
    vault is unlocked, then POST key + (if captured) session token.
    Returns True when a grant was stored."""
    session = attach_page(cdp, target["targetId"])
    if not session:
        log("capture: attach failed")
        return False
    install_token_hook(cdp, session)
    deadline = time.time() + VAULT_KEY_TIMEOUT_S
    last_why = None
    while time.time() < deadline:
        val = eval_js(cdp, session, KEY_JS)
        if isinstance(val, dict) and val.get("ok"):
            tok = collect_refresh_token(cdp, session)
            log(f"vault unlocked — capturing (uid={val.get('uid', '?')}"
                + (" +session)" if tok else ", no session leg)"))
            return post_grant(owner, val["key"], session=tok)
        why = val.get("why") if isinstance(val, dict) else "?"
        if why != last_why:
            log(f"vault key not ready: {why}")
            last_why = why
        time.sleep(VAULT_POLL_S)
    log("capture timeout (vault never unlocked within "
        f"{int(VAULT_KEY_TIMEOUT_S)}s)")
    return False


def capture_session_leg(cdp, target, owner):
    """Spec 59: upgrade path — the key grant already exists; watch for
    the SSO round-trip's refresh token (armed hook) and POST it as the
    session-only upgrade. Returns True when the grant became usable."""
    session = attach_page(cdp, target["targetId"])
    if not session:
        log("session-leg: attach failed")
        return False
    install_token_hook(cdp, session)
    deadline = time.time() + VAULT_KEY_TIMEOUT_S
    last_why = None
    while time.time() < deadline:
        tok = collect_refresh_token(cdp, session)
        if tok:
            log("refresh token captured via SSO round-trip — upgrading grant")
            return post_session(owner, tok)
        # Belt-and-braces: if the user unlocks while we wait, capture the
        # full grant (key + session) — covers a revoked/absent key too.
        val = eval_js(cdp, session, KEY_JS)
        why = val.get("why") if isinstance(val, dict) else "?"
        if isinstance(val, dict) and val.get("ok"):
            tok = collect_refresh_token(cdp, session)
            log(f"vault unlocked during session-leg watch (uid="
                f"{val.get('uid', '?')}" + (" +session)" if tok else ")"))
            return post_grant(owner, val["key"], session=tok)
        if why != last_why:
            log(f"session-leg: waiting for SSO round-trip ({why})")
            last_why = why
        time.sleep(VAULT_POLL_S)
    log("session-leg: no refresh token captured within "
        f"{int(VAULT_KEY_TIMEOUT_S)}s (no SSO round-trip?)")
    return False


# ---------- main loop ----------
username = password = mfa_seed = None
# Spec 66 (2026-08-25): per-slot-owner broker creds. The old shared
# static sso-creds.b64 (bot account "spike-user" / p41…) auto-filled
# the SAME identity into EVERY user's session — montigaud's kiosk
# auto-logged into the vault SSO as spike-user (Tigo: security breach).
# Now the broker reads the CURRENT slot owner's per-user creds from
# /data/sessions/<owner>/grant/sso-creds.json (the owner's own vault
# identity), so a broker login always logs in as the slot owner.
OWNER_CREDS_FILE = os.environ.get(
    "SSO_OWNER_CREDS_FILE", "/data/sessions/__OWNER__/grant/sso-creds.json")
_owner_cache = {}


def _owner() -> str:
    """Compatibility accessor over the canonical restart-api marker."""
    return slot_owner()


def _owner_creds_file(owner=None) -> str:
    o = (owner or slot_owner() or "").strip().lower()
    if not o:
        return ""
    return OWNER_CREDS_FILE.replace("__OWNER__", o)


def load_creds(owner=None):
    """Read per-slot-owner creds (b64 JSON: username/password) for the
    CURRENT owner into memory. PER-USER ONLY (spec 67/68): the legacy
    shared sso-creds.b64 fallback is REMOVED — a broker login must always
    use the current slot owner's own Vaultwarden identity, never a shared
    one. Returns False when the owner has no per-user creds file yet
    (broker then waits for the owner's own capture via /connect)."""
    global username, password
    owner = (owner or slot_owner() or "").strip().lower() or None
    f = _owner_creds_file(owner)
    if owner and f and os.path.exists(f):
        try:
            raw = open(f, "rb").read()
            creds = json.loads(base64.b64decode(raw))
            u = creds.get("username", "")
            p = creds.get("password", "")
            if u and p:
                username, password = u, p
                _owner_cache["owner"] = owner
                log(f"creds loaded for slot owner {owner} (per-user file)")
                return True
            log("ERROR: owner creds payload malformed")
            return False
        except Exception as e:
            log(f"ERROR: owner creds load failed: {type(e).__name__}: {e}")
            return False
    # No shared fallback (spec 66/67): if the owner has no per-user creds
    # file, fail closed and wait for the owner's own capture — never log
    # into the vault with another user's identity.
    if owner:
        log(f"no per-user creds for owner {owner} — waiting for the "
            "owner's own Vaultwarden login (no shared creds)")
    return False


# ---------- Spec 73 (D2) — grant-based owner login ----------
def _vault_client():
    """Lazy import of the slot-side vault-client so the broker starts
    even when the module is absent (fail-closed at login time)."""
    try:
        import importlib.util
        os.environ["CB_SLOT_SCRIPTS"] = SLOT_SCRIPTS_DIR
        path = os.path.join(SLOT_SCRIPTS_DIR, "vault_client.py")
        spec = importlib.util.spec_from_file_location("vault_client_d2", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log(f"vault-client unavailable: {type(e).__name__}")
        return None


def _ensure_login(owner):
    """Resolve the CURRENT owner's SSO login material (spec 73):

      1. grant path (vault-client): the owner's OWN GrantHub grant →
         vault sync → the SSO login item → username/password (+ TOTP
         seed when the item carries one);
      2. legacy per-owner sso-creds.json file (spec 66/68 convenience;
         carries no seed — chat-ask applies).

    Never a shared identity (spec 66/67)."""
    global username, password, mfa_seed
    vc = _vault_client()
    if vc:
        try:
            items = vc.login_items(owner)
            it = vc.find_ssologin(items,
                                  item_id=SSO_VAULT_ITEM_ID or None,
                                  exact_name=SSO_VAULT_ITEM)
            if it:
                if it.get("org_key_missing"):
                    log("D2: SSO item found but org key missing — "
                        "cannot decrypt its fields")
                if it.get("username") and it.get("password"):
                    username = it["username"]
                    password = it["password"]
                    mfa_seed = it.get("totp_secret")
                    log(f"creds loaded for slot owner {owner} (grant path)")
                    return True
        except Exception as e:
            log(f"grant login read failed: {type(e).__name__}")
            # A configured vault selection that is zero/duplicate/invalid is
            # a security failure, not permission to fall back to another
            # credential source.
            if type(e).__name__ == "VaultItemSelectionError":
                return False
    if load_creds(owner):
        mfa_seed = None
        log("creds from legacy per-owner file (no TOTP seed — chat-ask)")
        return True
    return False


def handle_login(cdp, target, owner, heartbeat,
                 generation=None, revalidate=None, before_cookie=None):
    """Identification + MFA; success requires fresh owner-bound TinyAuth."""
    if fill_and_submit(cdp, target):
        if revalidate is not None and not revalidate():
            log("login completed after owner/generation changed — rejecting")
            return False
        if not validate_session_after_login(cdp, owner, before_cookie):
            log("login left auth origins but owner-bound session is invalid")
            return False
        log("login attempt finished OK")
        return True
    log("identification submitted — watching for MFA stage")
    st = handle_mfa(cdp, target, owner, mfa_seed, heartbeat,
                    generation=generation, revalidate=revalidate)
    if st == "ok":
        if revalidate is not None and not revalidate():
            log("MFA completed after owner/generation changed — rejecting")
            return False
        if not validate_session_after_login(cdp, owner, before_cookie):
            log("MFA finished but owner-bound session is invalid")
            return False
        log("login attempt finished OK (MFA)")
        return True
    log("login attempt finished "
        + ("waiting for human (MFA)" if st == "waiting" else "FAILED"))
    return False


def main():
    global username, password  # reset on owner change (stale-identity guard)
    log(f"start (browser CDP {CDP_HTTP}, creds {CREDS_FILE}, poll {POLL_S}s)")
    handling_target = None
    missing_notified = False
    vault_handling_target = None
    # D3.2: the slot identity (.slot-user.json) is written by restart-api on
    # the router's /identify push and CHANGES as slots are reassigned
    # (offer/expire/release). Read it every pass and capture under the
    # CURRENT owner — a startup-only read captures grants under a stale
    # identity (observed: broker armed for montigaud while spike-user held
    # the slot → /connect/status never flipped for the real user).
    last_owner = None
    last_generation = None
    # Spec 59: rotation watcher — the vault SPA refreshes its own tokens
    # periodically; each refresh ROTATES the refresh token (old one is
    # revoked server-side), which would silently kill the stored session
    # leg. While a vault tab is present, re-collect + re-post any NEW
    # token every ROTATION_COLLECT_S (cheap attach + eval).
    last_collect = [0.0]
    ROTATION_COLLECT_S = 30.0
    # D15 B/C session state is a unit so every assignment generation—also
    # same-email reassignment—resets timers and forces one owner-bound SSO.
    session_state = {}
    reset_session_state(session_state, None)
    # Spec 55: watchdog — a single stalled loop pass (wedged Chrome/neko,
    # a CDP socket that ignores its timeout, a frame-parsing spin) can
    # freeze the broker forever (observed 2026-08-24: silent 10+ min while
    # Chrome came up → capture dead). The main loop refreshes the heartbeat
    # each pass; if it goes stale, force-exit so supervisord autorestart
    # recovers the daemon.
    HEARTBEAT_STALE_S = 90
    heartbeat = [time.time()]

    def _watchdog():
        while True:
            time.sleep(10)
            if time.time() - heartbeat[0] > HEARTBEAT_STALE_S:
                log("watchdog: main loop stalled — forcing exit "
                    "(supervisord autorestart)")
                os._exit(1)

    threading.Thread(target=_watchdog, daemon=True).start()
    while True:
        heartbeat[0] = time.time()
        # Identity generation includes marker timestamp so reassignment to the
        # same email is still a new security context.
        generation = marker_snapshot()
        owner = generation[0] if generation else None
        grant_capture_armed = bool(owner and BROKER_TOKEN)
        if generation != last_generation:
            # A generation change resets target suppression even when the
            # owner email is unchanged.
            handling_target = None
            missing_notified = False
            username = password = mfa_seed = None
            _owner_cache = {}
            reset_session_state(session_state, generation)
            last_generation = generation
        if owner != last_owner:
            # Spec 67/68 stale-identity guard: a previous owner's creds
            # must never persist into the next owner's session. Reset the
            # in-memory username/password (and D2 TOTP seed) on every
            # owner change so the next login is re-resolved against the
            # NEW owner's per-user material only.
            if username is not None or password is not None or mfa_seed is not None:
                log(f"owner change {last_owner} -> {owner}: clearing "
                    "in-memory creds (stale-identity guard)")
                username = password = mfa_seed = None
                _owner_cache = {}
            if owner and not BROKER_TOKEN:
                log("WARN: slot owner present but no per-slot broker token "
                    "configured — capture disabled")
            log(f"slot owner: {owner} — GrantHub capture "
                + ("armed" if grant_capture_armed else "disabled"))
            last_owner = owner
        try:
            cdp = CDP(int(CDP_HTTP.rsplit(":", 1)[1]))
        except Exception as e:
            log(f"CDP unreachable ({type(e).__name__}) — retrying")
            time.sleep(POLL_S)
            continue
        try:
            # D15 B/C session-health controller. It only operates while a
            # canonical owner marker exists, never opens a tab, and reloads
            # only a pre-existing trusted PMO City application page. On
            # restart/recreate the broker naturally reconnects and this check
            # resumes; a missing cookie is healed by the same Authentik watcher.
            now = time.time()
            target_infos = None
            if (owner and now - session_state["last_session_check"]
                    >= SESSION_CHECK_S):
                session_state["last_session_check"] = now
                h = session_cookie_health(cdp, now=now)
                if h["status"] != session_state["last_session_status"]:
                    ttl = h.get("ttl_s")
                    suffix = (f", ttl={int(ttl)}s"
                              if isinstance(ttl, (int, float)) else "")
                    log(f"session health: {h['status']}{suffix}")
                    session_state["last_session_status"] = h["status"]
                # Every new assignment generation must receive a fresh cookie,
                # even if an old one unexpectedly survived the profile guard.
                need_relogin = (session_state["owner_refresh_required"]
                                or h.get("relogin"))
                if (need_relogin and now - session_state["last_relogin_request"]
                        >= SESSION_RELOGIN_COOLDOWN_S):
                    tr = cdp.cmd("Target.getTargets")
                    target_infos = tr.get("result", {}).get("targetInfos", [])
                    app = find_session_probe_target(target_infos)
                    if app:
                        if request_session_relogin(cdp, app):
                            session_state["last_relogin_request"] = now
                            session_state["owner_refresh_required"] = False
                            log("session refresh requested on existing app tab")
                        else:
                            log("session refresh request failed")
                    elif h["status"] != "missing":
                        log("session refresh pending — no trusted app tab")

            target = find_login_target(cdp)
            if target:
                if target["targetId"] == handling_target:
                    time.sleep(POLL_S)
                    continue
                if (username is None or password is None) and not _ensure_login(owner):
                    if not missing_notified:
                        log("login tab detected, no owner login material — waiting")
                        missing_notified = True
                    time.sleep(POLL_S)
                    continue
                missing_notified = False
                handling_target = target["targetId"]
                log("login tab detected — attempting broker login")
                revalidate = lambda g=generation: marker_snapshot() == g
                try:
                    before_cookie = _exact_session_cookie(cdp)
                except Exception as e:
                    # Ambiguity/telemetry failure is not the same as a proven
                    # absence. Defer rather than weaken fresh-cookie proof.
                    log(f"pre-login cookie snapshot failed: {type(e).__name__}")
                    handling_target = None
                    time.sleep(POLL_S)
                    continue
                ok = handle_login(cdp, target, owner, heartbeat,
                                  generation=generation,
                                  revalidate=revalidate,
                                  before_cookie=before_cookie)
                # single-shot per target: never re-fill a completed login;
                # a fresh redirect page (new target id) is handled again.
                # On 'waiting' the human may finish in the kiosk; the same
                # target stays handled until it leaves auth origins.
            else:
                handling_target = None
                missing_notified = False
            if grant_capture_armed:
                vt = find_vault_target(cdp)
                if vt:
                    tid = vt["targetId"]
                    if tid != vault_handling_target:
                        st = grant_status(owner) or {}
                        if st.get("usable"):
                            log("grant fully usable — not re-capturing")
                            vault_handling_target = tid
                        elif st.get("shared"):
                            log("grant key present, session leg missing — "
                                "watching for SSO refresh-token capture")
                            vault_handling_target = tid
                            ok = capture_session_leg(cdp, vt, owner)
                            if ok:
                                log("session leg captured — grant now usable")
                            else:
                                log("session leg not captured yet — will retry")
                                vault_handling_target = None
                        else:
                            log("vault tab detected — watching for unlock")
                            vault_handling_target = tid
                            ok = capture_vault_key(cdp, vt, owner)
                            if ok:
                                log("grant captured + stored")
                            else:
                                log("capture did not complete — will retry")
                                vault_handling_target = None
                    elif time.time() - last_collect[0] > ROTATION_COLLECT_S:
                        # Spec 59 rotation watcher: grant already usable —
                        # still watch for a ROTATED refresh token (the SPA
                        # refreshes its own session; each refresh revokes
                        # the stored token server-side). Re-collect +
                        # re-post silently keeps the store fresh.
                        last_collect[0] = time.time()
                        try:
                            sid = attach_page(cdp, vt["targetId"])
                            if sid:
                                tok = collect_refresh_token(cdp, sid)
                                if tok:
                                    ok = post_session(owner, tok)
                                    log("rotation watcher: stored session "
                                        + ("updated" if ok
                                           else "update FAILED"))
                        except Exception as e:
                            log(f"rotation watcher error: {type(e).__name__}")
                else:
                    vault_handling_target = None
        except Exception as e:
            log(f"loop error: {type(e).__name__}: {e}")
        finally:
            cdp.close()
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
