#!/usr/bin/env python3
"""S7 v2 router — fleet front door, spec 31 queue + session limits (v3).

Reads Remote-Email (tinyauth forwardAuth authResponseHeaders) → resolves the
user's SLOT via a sticky assignment map (state volume) → proxies raw TCP:

  Host cloudbrowser.<domain>  → slot-<k>:8081   (UI, /ws WebSocket, WebRTC signaling)
  Host cloudfiles.<domain>    → slot-<k>:9231   (per-slot downloads surface, FR-12/D8)

Dispatch is by HOST, not path (D.3). Raw-socket proxy: supports HTTP
keep-alive AND WebSocket upgrade (neko's client connects /ws — a urllib
proxy cannot relay WS, so we pump sockets).

Spec 31 (2026-08-21) — unified wait queue + session duration limits:
  - Human entry flow: SSO → router root → if a slot is free → LANDING PAGE
    with an "Open Browser" button (href carries ?pwd=<NEKO_PASSWORD>&usr=
    <email> — neko v2.9.0's client auto-logins from these URL params and
    strips them via pushState, so the neko login screen is never shown;
    SSO is the only gate). If no slot free → QUEUE PAGE (position, ETA,
    waiting list, auto-refresh) — replaces the old static 503 BUSY_PAGE.
  - Max-duration reaper: the router owns the session clock (sessions map);
    when an active session exceeds its tier max (CB_HUMAN_MAX_SESSION_MIN /
    CB_AGENT_MAX_SESSION_MIN) it POSTs slot /suspend (idempotent), and marks
    the user's archive reason=expired → their next visit lands on the QUEUE
    page, never the neko login ("queue again to reclaim", spec 31 §9).
  - Idle suspend (spec 29) still archive-wakes (reason=idle) — walking away
    is not a session end; expiry is.
  - Adaptive ETA: rolling median of the last ~50 completed session
    durations per tier; cold start → tier max ÷ 2 (spec 31 §12 Q1).
  - Agent API (spec 31 §8): POST /queue, GET /queue/<id>, DELETE /queue/<id>
    (Bearer token = CB_AGENT_TOKEN; 501 when unset). Agents may also read
    /fleet/status (extended with queue depth by type).
  - Admin jump (CB_ADMIN_EMAILS): priority=1 entries sit at the type head.

Spec 29 idle suspend/resume — router is the fleet coordinator (sticky map +
archive registry): POST /fleet/release {user, reason} from the suspending
SLOT (idle=resumable, expired=re-queue); archive wake grabs the first free
slot and POSTs /wake {user}; /identify push + sweep keep the reaper named.

Header trust: only reachable behind Traefik+tinyauth (401 gate). A client
could forge Remote-Email — tinyauth APPENDS its header, so the LAST
occurrence wins (this handler reads the last). The /fleet/* and /queue/*
control endpoints are internal-only by construction (Remote-Email presence
check + token).
"""
import base64
import html
import json
import os
import re as _re
import secrets
import select
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import granthub  # GrantHub shared lib (grant store + AES-GCM wrap/unwrap)

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
AUTO_CREATE = os.environ.get("AUTO_CREATE_SESSIONS", "false").lower() == "true"
N_SLOTS = int(os.environ.get("N_SLOTS", "2"))
SLOT_PORT = int(os.environ.get("SLOT_PORT", "8081"))
FILES_PORT = int(os.environ.get("FILES_PORT", "9231"))
# Internal compose-network calls always use the container port. The host
# publishes slot-1/slot-2 as 9230/9231, but slot-N DNS resolves to the
# service itself and restart-api listens on 9230 in both containers.
SLOT_API_CONTAINER_PORT = 9230
FILES_URL = os.environ.get("FILES_URL", "https://cloudfiles.dev01.pmo.city/")
SECRETS_URL = os.environ.get("SECRETS_URL", "https://secrets.pmo.city/")
SWEEP_INTERVAL = float(os.environ.get("IDENTIFY_SWEEP_INTERVAL", "30"))
STATE_FILE = os.environ.get("ROUTER_STATE", "/data/state/router-state.json")

# --- Spec 31: qualified env surface (read once at boot, logged) ---------
CB_HUMAN_SLOTS = int(os.environ.get("CB_HUMAN_SLOTS", "1"))
CB_AGENT_SLOTS = int(os.environ.get("CB_AGENT_SLOTS", "0"))
CB_HUMAN_MAX_SESSION_MIN = float(os.environ.get("CB_HUMAN_MAX_SESSION_MIN", "5"))
CB_AGENT_MAX_SESSION_MIN = float(os.environ.get("CB_AGENT_MAX_SESSION_MIN", "240"))
CB_AGENT_QUEUE_TIMEOUT_S = float(os.environ.get("CB_AGENT_QUEUE_TIMEOUT_S", "120"))
CB_QUEUE_POLL_INTERVAL_S = float(os.environ.get("CB_QUEUE_POLL_INTERVAL_S", "5"))
CB_ADMIN_EMAILS = {
    e.strip().lower() for e in os.environ.get("CB_ADMIN_EMAILS", "").split(",") if e.strip()
}
CB_QUEUE_SHOW_EMAILS = os.environ.get("CB_QUEUE_SHOW_EMAILS", "true").lower() == "true"
CB_AGENT_TOKEN = os.environ.get("CB_AGENT_TOKEN", "")
CB_REAPER_INTERVAL_S = float(os.environ.get("CB_REAPER_INTERVAL_S", "10"))
# Spec 36 §21: how long an offered queue entry may sit before the offer
# expires and the user goes to the BACK of the queue (one-shot chance).
CB_OFFER_GRACE_S = float(os.environ.get("CB_OFFER_GRACE_S", "60"))
# Spec 77 (2026-08-28): ghost-offer livelock — after
# CB_OFFER_BACKOFF_THRESHOLD consecutive offer-expiries for the same
# (email, slot) pair within CB_OFFER_BACKOFF_WINDOW_S, the entry moves
# to status=backed_off (off the offer scan) and sits there invisibly
# for CB_OFFER_BACKOFF_COOLDOWN_S before being silently dropped. The
# counter resets on a successful take of that slot by the same email.
CB_OFFER_BACKOFF_THRESHOLD = int(os.environ.get("CB_OFFER_BACKOFF_THRESHOLD", "3"))
CB_OFFER_BACKOFF_WINDOW_S = float(os.environ.get("CB_OFFER_BACKOFF_WINDOW_S", "1800"))
CB_OFFER_BACKOFF_COOLDOWN_S = float(os.environ.get("CB_OFFER_BACKOFF_COOLDOWN_S", "900"))
NEKO_PASSWORD = os.environ.get("NEKO_PASSWORD", "neko")
# Spec 39: wedged-neko auto-rescue. CB_RESET_AFTER = consecutive stuck
# watchdog polls (each poll is 2 s) before the client asks for a rescue;
# CB_RESET_COOLDOWN_S = min seconds between rescues (client + server side).
# Spec 40: CB_STREAM_AFTER = consecutive polls with a stalled/absent video
# stream (blank-page wedge) before the same rescue path fires.
CB_RESET_AFTER = int(os.environ.get("CB_RESET_AFTER", "10"))
CB_STREAM_AFTER = int(os.environ.get("CB_STREAM_AFTER", "10"))
CB_RESET_COOLDOWN_S = float(os.environ.get("CB_RESET_COOLDOWN_S", "60"))
# Spec 54 (2026-08-24, Tigo): the login-stuck rescue loop was UNBOUNDED —
# each rescue reloads the page, stuck resets, and the wedge re-accumulates
# → restart-neko every cooldown window under an active user (observed 2×
# before the session expired). Cap the escalation per session; beyond the
# budget /fleet/rescue is a harmless no-op and the session just expires
# into the queue page. Budget resets on every new session (wake/assign/
# offer-take).
CB_MAX_RESCUES = int(os.environ.get("CB_MAX_RESCUES", "2"))

# --- Spec 37: unified top bar (GrantHub "Shared" pill) ------------------
# GRANTHUB_URL: where the Shared pill navigates. GRANTHUB_STATUS_URL:
# optional JSON endpoint {"shared": bool} keyed by Remote-Email; when
# unset/unreachable the pill shows "Not Shared" (never a false green).
GRANTHUB_URL = os.environ.get("GRANTHUB_URL", "https://cloudbrowser.dev01.pmo.city/connect")
GRANTHUB_STATUS_URL = os.environ.get("GRANTHUB_STATUS_URL", "")

# --- Spec 47 GrantHub (GH.1–GH.8) ---------------------------------------
# GrantHub lives IN the router (same origin, tinyauth-gated). Grant store =
# per-user folders under GRANT_ROOT (the shared `sessions` volume; mounted
# into the router service for GH.1). Broker/admin tokens fail closed when
# unset (endpoints return 501/403).
GRANT_ROOT = os.environ.get("GRANT_ROOT", "/data/sessions")
CB_GRANTHUB_BROKER_TOKEN = os.environ.get("CB_GRANTHUB_BROKER_TOKEN", "")
CB_GRANTHUB_ADMIN_TOKEN = os.environ.get("CB_GRANTHUB_ADMIN_TOKEN", "")

# --- Audit B3/B4 (spec 66 isolation): PER-SLOT broker credentials --------
# Each slot gets its OWN bearer (CB_SLOT_<n>_TOKEN, e.g. the Coolify magic
# var SERVICE_PASSWORD_64_SLOT<n>BROKER). The router derives the calling
# slot from the bearer and binds every broker operation to the CURRENT
# owner of that slot in _state["slots"] — a supplied Remote-Email that is
# not the server-derived owner is rejected (403). The legacy shared
# CB_GRANTHUB_BROKER_TOKEN stays as a fallback ONLY when no per-slot token
# is configured (test/single-slot mode).
_SLOT_TOKENS = {}
for _sn in range(1, int(os.environ.get("N_SLOTS", "2")) + 1):
    _t = os.environ.get(f"CB_SLOT_{_sn}_TOKEN", "")
    if _t:
        _SLOT_TOKENS[_sn] = _t


def _slot_for_bearer(bearer: str):
    """Slot number whose per-slot token matches the bearer, else None."""
    if not bearer:
        return None
    for _sn, _t in _SLOT_TOKENS.items():
        if _t and bearer == _t:
            return _sn
    return None


def _slot_owner(k):
    """Server-derived owner of slot k from the router's own state."""
    try:
        return (_state["slots"].get(str(k)) or "").strip().lower() or None
    except Exception:
        return None

# --- Spec 73 (D2) — OTP code-exchange (chat-ask leg) ----------------------
# The broker raises a code request when the SSO login item carries no TOTP
# seed; the agent submits the employee's one-time code; the broker fetches
# it ONCE. The code lives ONLY in this in-memory dict — never persisted,
# never logged, dropped on expiry (CB_OTP_TTL_S) or router restart.
CB_OTP_AGENT_TOKEN = os.environ.get("CB_OTP_AGENT_TOKEN", "")
CB_OTP_TTL_S = float(os.environ.get("CB_OTP_TTL_S", "180"))
# Audit B10: one-shot challenge-bound requests. Keyed by an opaque random
# request id, bound to {slot, owner}; exactly one submit and one fetch;
# consumed atomically (replay/replacement/owner-reassignment fail).
_otp_pending = {}  # request_id -> {"requested_at","submitted_at","slot",
                   #               "owner","target","code"}
_otp_lock = threading.Lock()


def _shared_state(email: str) -> tuple:
    """Return (label, css_class) for the GrantHub Shared pill.

    Spec 47: GrantHub is in-process — read the per-user grant store
    directly (authoritative, no HTTP roundtrip). GRANTHUB_STATUS_URL stays
    as an external override for components that cannot read the store
    (e.g. title-proxy on the slots). Spec 59: GREEN ONLY when the grant
    is USABLE — both the vault key AND the session-token leg present.
    Never a false green."""
    if GRANT_ROOT:
        try:
            if granthub.status(GRANT_ROOT, email).get("usable"):
                return ("🔗 Shared", "cb-shared")
        except Exception:
            pass
    if GRANTHUB_STATUS_URL:
        try:
            req = urllib.request.Request(
                GRANTHUB_STATUS_URL,
                headers={"Remote-Email": email, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                if json.loads(r.read().decode("utf-8", "replace")).get("usable"):
                    return ("🔗 Shared", "cb-shared")
        except Exception:
            pass
    return ("🔗 Not Shared", "cb-noshared")


def _whitelisted_surface(url: str) -> str | None:
    """Spec 48: accept only the configured capture surfaces for kiosk-open.

    Same-origin paths (e.g. /connect) and the configured FILES_URL /
    SECRETS_URL / GRANTHUB_URL (exact or sub-path). Everything else is
    rejected, so a crafted ?goto= can't drive the kiosk to arbitrary sites
    and the /kiosk/open endpoint can't be abused as an open redirect.
    Returns the normalized url or None."""
    u = (url or "").strip()
    if not u:
        return None
    if u.startswith("/") and not u.startswith("//"):
        return u  # same-origin path (/connect, /connect/status, …)
    if "://" not in u:
        return None
    for base in (FILES_URL, SECRETS_URL, GRANTHUB_URL):
        b = (base or "").strip().rstrip("/")
        if not b:
            continue
        if u.rstrip("/") == b or u.startswith(b + "/"):
            return u
    return None

# Pool slot ranges: 1..CB_HUMAN_SLOTS are human (neko UI), the next
# CB_AGENT_SLOTS are agent (bare chrome/CDP). Legacy N_SLOTS stays as a
# fallback upper bound for the human pool during migration.
_HUMAN_KS = list(range(1, CB_HUMAN_SLOTS + 1))
_AGENT_KS = list(range(CB_HUMAN_SLOTS + 1, CB_HUMAN_SLOTS + CB_AGENT_SLOTS + 1))
MAX_SESSION_S = {
    "human": CB_HUMAN_MAX_SESSION_MIN * 60.0,
    "agent": CB_AGENT_MAX_SESSION_MIN * 60.0,
}
def _next_eid():
    """Unique queue entry id from the PERSISTED sequence (spec 36 §19).

    The old in-memory counter reset to 1 on every router restart, so a
    fresh entry could reuse the id of an entry that survived in the
    persisted queue — the live fleet had TWO 'q-1' entries and _eta_for's
    id lookup handed both users position 1. Callers must hold _lock (all
    enqueue paths do); the bump is persisted by the caller's save_state."""
    _state["queue_seq"] = _state.get("queue_seq", 0) + 1
    return f"q-{_state['queue_seq']:x}"
_queue_lock = threading.Lock()

print(f"[router] v3 spec31: human_slots={CB_HUMAN_SLOTS} "
      f"agent_slots={CB_AGENT_SLOTS} human_max={CB_HUMAN_MAX_SESSION_MIN}m "
      f"agent_max={CB_AGENT_MAX_SESSION_MIN}m admin={sorted(CB_ADMIN_EMAILS)} "
      f"agent_token={'set' if CB_AGENT_TOKEN else 'unset'}", flush=True)


# --- HTML pages ----------------------------------------------------------
# PMO City brand mark (from https://pmo.city/ navbar, 2026-08-22) — used as
# the favicon on every CloudBrowser surface (queue/landing pages here; the
# session page via title-proxy; CloudFiles via downloads-api). Tigo: "for all
# pages the favicon should be the PMO City logo and not the Neko cat".
_PMO_LOGO = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 470">'
             '<path fill-rule="evenodd" fill="#3D6475" '
             'd="M 60,235 A 190,190 0 1,0 440,235 A 190,190 0 1,0 60,235 Z '
             'M 118,235 A 132,132 0 1,1 382,235 A 132,132 0 1,1 118,235 Z"/>'
             '<rect x="22" y="210" width="456" height="50" fill="#3D6475"/>'
             '<circle cx="250" cy="235" r="72" fill="#6DD5B5"/></svg>')
_PMO_LOGO_B64 = base64.b64encode(_PMO_LOGO.encode("utf-8")).decode("ascii")
_FAVICON_LINK = ('<link rel="icon" type="image/svg+xml" '
                 f'href="data:image/svg+xml;base64,{_PMO_LOGO_B64}">')


def _landing_page(email: str) -> str:
    """Slot ready → 'Open Browser' button. The href carries ?pwd=&usr= so
    neko v2.9.0's client auto-logins and strips the params (no login UI)."""
    pwd = urllib.parse.quote(NEKO_PASSWORD, safe="")
    usr = urllib.parse.quote(email, safe="")
    max_min = int(CB_HUMAN_MAX_SESSION_MIN)
    top_bar = _top_bar(email, variant="landing")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>CloudBrowser: {email}</title>
{_FAVICON_LINK}
<style>
:root{{color-scheme:dark}}
body{{background:#0f1115;color:#e6e8ee;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
display:flex;flex-direction:column;min-height:100vh;margin:0}}
/* neko top bar duplicate (same as the session page, minus the burger) */
.header{{background:#202225;height:40px;flex-shrink:0;display:flex;align-items:center}}
.header .neko{{display:flex;align-items:center;justify-content:flex-start;flex:1;width:150px;
margin-left:20px;color:#dcddde;text-decoration:none}}
.header .neko img{{display:block;height:30px;margin-right:10px}}
.header .neko span{{font-size:30px;line-height:30px;font-family:Whitney,'Helvetica Neue',Helvetica,Arial,sans-serif}}
.header .neko span b{{font-weight:900}}
.header .menu{{justify-self:flex-end;margin-right:10px;white-space:nowrap;
list-style:none;margin:0;padding:0;text-align:right}}
.header .menu li{{display:inline-block;margin-right:10px;padding:0;border-top:none}}
.header .menu li a.cb-tool{{display:inline-flex;align-items:center;font-size:12px;font-weight:500;
color:#c9cdd8;background:rgba(255,255,255,.08);padding:3px 9px;border-radius:4px;
text-decoration:none;white-space:nowrap}}
.header .menu li a.cb-tool:hover{{background:rgba(255,255,255,.2);color:#fff}}
.header .menu li a.cb-tool.pinned{{background:rgba(80,160,255,.35);color:#fff;box-shadow:inset 0 0 0 1px rgba(80,160,255,.6)}}
.header .menu li.cb-email-li{{display:inline-flex;align-items:center;margin-right:14px;
pointer-events:none;user-select:none}}
.header .menu li .cb-email{{font-size:13px;font-weight:500;color:rgba(255,255,255,.72);letter-spacing:.2px;white-space:nowrap}}
.header .menu li.cb-sep-li{{display:inline-flex;align-items:center;margin:0 6px;padding:0}}
.header .cb-sep{{display:block;width:1px;height:14px;background:rgba(255,255,255,.15)}}
.header .menu li a.cb-tool.cb-shared{{color:#22c55e}}
.header .menu li a.cb-tool.cb-noshared{{color:#ef4444}}
.card{{margin:auto}}
.card{{background:#161a22;border:1px solid #242a36;border-radius:14px;padding:42px 50px;max-width:430px;text-align:center}}
h1{{font-size:22px;margin:0 0 6px;font-weight:650}}
p.sub{{color:#8b93a5;margin:0 0 28px;font-size:14px}}
.btn{{display:inline-block;background:#14b8a6;color:#06221e;font-weight:700;font-size:16px;
padding:14px 36px;border-radius:10px;text-decoration:none;transition:background .15s}}
.btn:hover{{background:#0ea597}}
.hint{{color:#5c6474;font-size:12px;margin-top:24px}}
</style></head>
<body>{top_bar}<div class="card">
<h1><b>C</b>loud<b>B</b>rowser</h1>
<p class="sub">Your browser session is ready, {email}</p>
<a class="btn" href="/?pwd={pwd}&usr={usr}">Open Browser</a>
<p class="hint">Session limit: {max_min} min — when it ends you queue again to reclaim.</p>
</div>
<script>
/* Spec 53: live-flip the GrantHub pill in the top bar (grant/revoke
   without reload — same poll the /connect card uses). */
(function(){{function paint(j){{var sh=!!(j&&j.ok&&j.usable);
var a=document.getElementById('ghPill');if(!a)return;
a.textContent=sh?'🔗 Shared':'🔗 Not Shared';
a.className='cb-tool '+(sh?'cb-shared':'cb-noshared');}}
function poll(){{fetch('/connect/status',{{cache:'no-store'}})
.then(function(r){{return r.json();}}).then(paint).catch(function(){{}});}}
poll();setInterval(poll,2000);}})();
</script>
</body></html>"""


def _top_bar(email: str, variant: str = "landing") -> str:
    """Desktop top bar (landing/queue pages) — brand + right-side pills.

    Spec 48 rev2 (capture-surface UX): CloudFiles + Secrets are ALWAYS
    plain main-browser links (target=_blank) — files must be downloadable
    on the main computer; inside the kiosk there is no way to get the file
    out. Only the GrantHub Shared pill enters the kiosk (goto param on the
    neko entry), where capture happens. On the queue page the GrantHub pill
    is hidden (no kiosk to capture in yet).

    Right side (spec 37, LOCKED): CloudFiles | Secrets·Shared | email —
    Secrets+Shared are ONE block (no separator between them); the Shared
    pill reflects GrantHub state (green "Shared" / red "Not Shared", never
    a false green). Brand: CloudBrowser (bold C + B)."""
    e = html.escape(email)
    s = html.escape(SECRETS_URL, quote=True)
    f = html.escape(FILES_URL, quote=True)
    g = html.escape(GRANTHUB_URL, quote=True)
    g_label, g_cls = _shared_state(email)
    brand = f"""\
<a class="neko">
    <img src="data:image/svg+xml;base64,PHN2ZyB2ZXJzaW9uPSIxLjEiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6eGxpbms9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkveGxpbmsiIHg9IjBweCIgeT0iMHB4IiB2aWV3Qm94PSIwIDAgMTAwIDEwMCIgeG1sOnNwYWNlPSJwcmVzZXJ2ZSI+CiAgPHJlY3QgeD0iMCIgeT0iNDQuMyIgd2lkdGg9IjEwMCIgaGVpZ2h0PSIxMS40IiBmaWxsPSIjNDA0RTVCIi8+CiAgPGNpcmNsZSBjeD0iNTAiIGN5PSI1MCIgcj0iMzcuOSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjNDA0RTVCIiBzdHJva2Utd2lkdGg9IjExLjQiLz4KICA8Y2lyY2xlIGN4PSI1MCIgY3k9IjUwIiByPSIxNS4yIiBmaWxsPSIjOEREM0IxIi8+Cjwvc3ZnPg==" alt="n.eko">
    <span><b>C</b>loud<b>B</b>rowser</span>
  </a>"""
    if variant == "queue":
        # Spec 48 rev2 (Tigo 2026-08-23): CloudFiles + Secrets are ALWAYS
        # plain main-browser links — files must be downloadable on the main
        # computer; inside the kiosk there is no way to get the file out.
        # CloudFiles is safe as a plain link even while queued: the router
        # routes to the requester's own area (their slot if assigned, else
        # slot-1) and downloads-api isolates per-user (archived area /
        # empty — never another user's live files). The GrantHub "Not
        # Shared" pill is hidden here (no kiosk to capture in yet).
        return f"""\
<div class="header">
  {brand}
  <ul class="menu">
    <li><a class="cb-tool" href="{f}" target="_blank" rel="noopener">📁 CloudFiles</a></li>
    <li class="cb-sep-li"><span class="cb-sep"></span></li>
    <li><a class="cb-tool" href="{s}" target="_blank" rel="noopener">🔒 Secrets</a></li>
    <li class="cb-sep-li"><span class="cb-sep"></span></li>
    <li class="cb-email-li"><span class="cb-email">{e}</span></li>
  </ul>
</div>
"""
    # CloudFiles + Secrets are ALWAYS plain main-browser links (Tigo
    # 2026-08-23): files must be downloadable on the main computer —
    # inside the kiosk there is no way to get the file out. So both are
    # target=_blank here; only the GrantHub Shared pill enters the kiosk
    # (capture happens there).
    pwd = urllib.parse.quote(NEKO_PASSWORD, safe="")
    usr = urllib.parse.quote(email, safe="")
    entry = f"/?pwd={pwd}&usr={usr}&goto="
    return f"""\
<div class="header">
  {brand}
  <ul class="menu">
    <li><a class="cb-tool" href="{f}" target="_blank" rel="noopener">📁 CloudFiles</a></li>
    <li class="cb-sep-li"><span class="cb-sep"></span></li>
    <li><a class="cb-tool" href="{s}" target="_blank" rel="noopener">🔒 Secrets</a></li>
    <li><a class="cb-tool {g_cls}" id="ghPill" href="{entry}{urllib.parse.quote(g, safe='')}" rel="noopener">{g_label}</a></li>
    <li class="cb-sep-li"><span class="cb-sep"></span></li>
    <li class="cb-email-li"><span class="cb-email">{e}</span></li>
  </ul>
</div>
"""


def _queue_page(email: str) -> str:
    """No slot free → queue page. Polls /queue/status (Remote-Email keys the
    entry); when the entry turns active the Open Browser button appears."""
    poll_ms = int(CB_QUEUE_POLL_INTERVAL_S * 1000)
    show = "true" if CB_QUEUE_SHOW_EMAILS else "false"
    max_min = int(CB_HUMAN_MAX_SESSION_MIN)
    top_bar = _top_bar(email, variant="queue")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>CloudBrowser: {email}</title>
{_FAVICON_LINK}
<style>
:root{{color-scheme:dark}}
body{{background:#0f1115;color:#e6e8ee;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
display:flex;flex-direction:column;min-height:100vh;margin:0}}
/* neko top bar duplicate (same as the session page, minus the burger:
   chat/settings are not available on the queue page) */
.header{{background:#202225;height:40px;flex-shrink:0;display:flex;align-items:center}}
.header .neko{{display:flex;align-items:center;justify-content:flex-start;flex:1;width:150px;
margin-left:20px;color:#dcddde;text-decoration:none}}
.header .neko img{{display:block;height:30px;margin-right:10px}}
.header .neko span{{font-size:30px;line-height:30px;font-family:Whitney,'Helvetica Neue',Helvetica,Arial,sans-serif}}
.header .neko span b{{font-weight:900}}
.header .menu{{justify-self:flex-end;margin-right:10px;white-space:nowrap;
list-style:none;margin:0;padding:0;text-align:right}}
.header .menu li{{display:inline-block;margin-right:10px;padding:0;border-top:none}}
.header .menu li a.cb-tool{{display:inline-flex;align-items:center;font-size:12px;font-weight:500;
color:#c9cdd8;background:rgba(255,255,255,.08);padding:3px 9px;border-radius:4px;
text-decoration:none;white-space:nowrap}}
.header .menu li a.cb-tool:hover{{background:rgba(255,255,255,.2);color:#fff}}
.header .menu li a.cb-tool.pinned{{background:rgba(80,160,255,.35);color:#fff;box-shadow:inset 0 0 0 1px rgba(80,160,255,.6)}}
.header .menu li.cb-email-li{{display:inline-flex;align-items:center;margin-right:14px;
pointer-events:none;user-select:none}}
.header .menu li .cb-email{{font-size:13px;font-weight:500;color:rgba(255,255,255,.72);letter-spacing:.2px;white-space:nowrap}}
.header .menu li.cb-sep-li{{display:inline-flex;align-items:center;margin:0 6px;padding:0}}
.header .cb-sep{{display:block;width:1px;height:14px;background:rgba(255,255,255,.15)}}
.header .menu li a.cb-tool.cb-shared{{color:#22c55e}}
.header .menu li a.cb-tool.cb-noshared{{color:#ef4444}}
.card{{margin:auto}}
.card{{background:#161a22;border:1px solid #242a36;border-radius:14px;padding:42px 50px;max-width:460px;text-align:center}}
h1{{font-size:22px;margin:0 0 6px;font-weight:650}}
p.sub{{color:#8b93a5;margin:0 0 22px;font-size:14px}}
.big{{font-size:34px;font-weight:800;color:#14b8a6;margin:6px 0 2px}}
.lbl{{color:#5c6474;font-size:12px;text-transform:uppercase;letter-spacing:.08em}}
#eta{{color:#c9d1de;font-size:14px;margin:14px 0}}
ul{{list-style:none;margin:10px auto 0;padding:0;text-align:center;font-size:14px;color:#c9d1de}}
li{{padding:4px 0}}
li .qn{{color:#14b8a6;font-weight:800;margin-right:8px}}
.sep{{border:none;border-top:1px solid #2a3140;margin:16px auto 8px;max-width:340px}}
.btn{{display:inline-block;background:#14b8a6;color:#06221e;font-weight:700;font-size:16px;
padding:14px 36px;border-radius:10px;text-decoration:none;margin-top:18px;transition:background .15s}}
.btn:hover{{background:#0ea597}}
.hidden{{display:none!important}}
.hint{{color:#5c6474;font-size:12px;margin-top:22px}}
</style></head>
<body>{top_bar}<div class="card">
<h1><b>C</b>loud<b>B</b>rowser</h1>
<p class="sub">All browsers are in use — you are in the queue</p>
<div class="lbl">Your position</div>
<div class="big" id="pos">…</div>
<div id="eta"></div>
<a id="btn" class="btn hidden" href="">Open Browser</a>
<p id="active" class="hint"></p>
<hr class="sep">
<ul id="waiting"></ul>
<p id="agents" class="hint"></p>
<p class="hint">Session limit: {max_min} min — when it ends you queue again to reclaim.</p>
</div>
<script>
const SHOW_EMAILS = {show};
const posEl = document.getElementById('pos');
const posLbl = document.querySelector('.lbl');
let countdownEndsAt = 0;
function fmtCd(s) {{
  s = Math.max(0, Math.ceil(s));
  const m = Math.floor(s/60), ss = s%60;
  return m + ':' + (ss<10?'0':'') + ss;
}}
setInterval(function() {{
  if (countdownEndsAt > 0) posEl.textContent = fmtCd((countdownEndsAt - Date.now())/1000);
}}, 1000);
async function tick() {{
  try {{
    const r = await fetch('/queue/status', {{cache:'no-store'}});
    const j = await r.json();
    const offered = j.status === 'offered' && (j.offer_ttl_s||0) > 0;
    const active = j.status === 'active';
    if (offered) {{
      // Grace countdown replaces the position (Tigo 2026-08-22: no "?")
      countdownEndsAt = Date.now() + j.offer_ttl_s*1000;
      posLbl.textContent = 'Offer expires in';
      posEl.textContent = fmtCd(j.offer_ttl_s);
    }} else if (active) {{
      countdownEndsAt = Date.now() + (j.session_ttl_s||0)*1000;
      posLbl.textContent = 'Session ends in';
      posEl.textContent = fmtCd(j.session_ttl_s||0);
    }} else {{
      countdownEndsAt = 0;
      posLbl.textContent = 'Your position';
      posEl.textContent = j.position ?? '?';
    }}
    const eta = j.eta_s;
    document.getElementById('eta').textContent = (offered || active)
      ? ''
      : (eta > 0
        ? '≈ ' + (eta >= 3600 ? (eta/3600).toFixed(1)+' h' : eta >= 60 ? Math.ceil(eta/60)+' min' : eta+' s')
        : '');
    const canOpen = (j.status === 'active' || j.status === 'offered') && j.open_url;
    const b = document.getElementById('btn');
    if (canOpen) {{
      b.href = j.open_url; b.classList.remove('hidden');
      // NOTE: do NOT clearInterval here — the poll MUST keep running so a
      // lapsed offer re-renders this page (label -> 'Your position', button
      // re-hidden by the guard below) instead of freezing at 0:00 with a
      // dead button (Tigo 2026-08-22: "it should reload with the user at
      // the bottom of the list").
    }} else {{
      // Zombie-button guard (Tigo 2026-08-22): a poll that returns waiting
      // must RE-HIDE a previously revealed button (offer lapsed, entry
      // demoted) — otherwise the page keeps offering a dead session.
      b.classList.add('hidden'); b.href = '';
    }}
    if (SHOW_EMAILS) {{
      const active = document.getElementById('active');
      active.textContent = (j.active_humans||[]).length > 0
        ? 'Active session: ' + j.active_humans.join(', ')
        : '';
    }}
    const ul = document.getElementById('waiting');
    ul.innerHTML = (j.waiting||[]).map(w =>
      '<li><b class="qn">'+w.pos+'.</b>'+
      (w.email||'').replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))+
      '</li>').join('');
    document.getElementById('agents').textContent =
      (j.agent_count||0) > 0 ? '…plus ' + j.agent_count + ' agent job' + (j.agent_count>1?'s':'') + ' waiting' : '';
  }} catch(e) {{}}
}}
// Spec 48 rev2 (Tigo 2026-08-23): queue-page pills are plain main-browser
// links (CloudFiles + Secrets, target=_blank) — files must be downloadable
// on the main computer. No pending-goto intent needed on the queue page.
setInterval(tick, {poll_ms});
tick();
</script>
</body></html>"""


# --- neko session watchdog (spec 31 §9 follow-up, 2026-08-21) -----------
# The neko SPA shows its own LOG IN screen when the session's WebSocket
# drops (idle suspend stops title-proxy; max-duration expiry suspends the
# slot; router/title-proxy restarts kill in-flight WS). The router injects
# this poller into the index it serves on the human entry flow
# (/?pwd=…&usr=…):
#   * state ≠ active            → bounce to the router root, which serves
#                                 the landing page (idle → resume) or the
#                                 queue page (expired → re-queue);
#   * state == active but the neko LOG IN screen (<neko-connect>) is up →
#     the session is fine, only the viewer WS dropped. Re-enter through
#     the router (/queue/status → open_url carries ?pwd=&usr=) so the
#     auto-login restores the stream — zero user action (Tigo 2026-08-22).
# "Never show the neko login" therefore holds for in-flight sessions too.
_WATCHDOG = r"""
<script>
/* CB session watchdog v2 — see router.py. Bounce to the router root when the
   session is no longer active; re-enter via ?pwd=&usr= when the session is
   active but the neko LOG IN screen is up (dropped viewer WebSocket).
   Spec 39: when a re-entry auto-login FAILS (neko keeps ?pwd= in the URL —
   it never strips the params on a wedged auth), the LOG IN would stick
   forever; escalate to POST /fleet/rescue so the slot restarts the neko app
   process (profile + tabs preserved). */
(function(){
  var MS = 2000;
  var RESCUE_AFTER = __RESCUE_AFTER__;
  var MAX_RESCUES = __MAX_RESCUES__;
  var COOLDOWN = __RESCUE_COOLDOWN_MS__;
  var STREAM_AFTER = __STREAM_AFTER__;
  var stuck = 0;
  var nextRescue = 0;
  var lastT = null, stillT = 0, noMediaT = 0;
  function loginScreen() {
    var el = document.querySelector('neko-connect');
    if (!el) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  /* Spec 40: blank-page wedge — neko accepts connections but never
     restarts its session pipeline. The viewer's <video> (inside
     .player-container) has no frames: currentTime stalls (live stream)
     or readyState never reaches HAVE_CURRENT_DATA. The client has no
     visibility/pause handlers, so a stalled playhead is a real dead
     stream. Also covers the app-never-mounted case (no login screen,
     no video element) — e.g. blank page with no DOM at all. */
  function streamDead() {
    var v = document.querySelector('.player-container video') ||
            document.querySelector('video');
    if (v) {
      var t = v.currentTime;
      if (v.readyState >= 2 && t > 0) {
        if (lastT !== null && t === lastT) { stillT += 1; } else { stillT = 0; }
        lastT = t;
        noMediaT = 0;
        return stillT >= STREAM_AFTER;
      }
      // readyState < 2 (no data ever) — count polls without frames.
      noMediaT += 1;
      lastT = null; stillT = 0;
      return noMediaT >= STREAM_AFTER;
    }
    // No video element: viewer app not mounted. Only escalate when the
    // login screen is ALSO absent for the whole window (boot normally
    // takes seconds; the window defaults to 20 s).
    noMediaT += 1;
    return noMediaT >= STREAM_AFTER;
  }
  function rescue(reason) {
    if (Date.now() < nextRescue) return;
    nextRescue = Date.now() + COOLDOWN;
    fetch("/fleet/rescue", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({requester:"watchdog", reason: reason})})
      .catch(function(){});
  }
  setInterval(function(){
    fetch("/fleet/my-status", {cache:"no-store"})
      .then(function(r){return r.json();})
      .then(function(d){
        if (!d || !d.state) return;
        if (d.state !== "active") { location.href = "/"; return; }
        if (loginScreen()) {
          if (location.search.indexOf("pwd=") !== -1) {
            // Re-entry auto-login was attempted but neko never stripped the
            // params — the auth wedged. Count it; escalate after
            // RESCUE_AFTER consecutive stuck polls. Spec 54: the budget is
            // capped per session (sessionStorage survives the rescue
            // reload); beyond it we stop restarting neko under the user —
            // the session expires into the queue page instead of looping.
            stuck += 1;
            if (stuck >= RESCUE_AFTER) {
              stuck = 0;
              var rc = 0;
              try { rc = parseInt(sessionStorage.getItem('cb_rescues') || '0', 10) || 0; } catch(e) {}
              if (rc < MAX_RESCUES) {
                try { sessionStorage.setItem('cb_rescues', String(rc + 1)); } catch(e) {}
                rescue("login-stuck");
              }
              location.href = "/";
            }
          } else {
            // Healthy drop: session active but viewer WS gone. Re-enter
            // through the router so the auto-login params restore it.
            fetch("/queue/status", {cache:"no-store"})
              .then(function(r){return r.json();})
              .then(function(j){
                if (j && j.status === "active" && j.open_url) {
                  stuck = 0;
                  location.href = j.open_url;
                }
              })
              .catch(function(){});
          }
        } else {
          stuck = 0;
          // Spec 54: healthy session → reset the rescue budget.
          try { sessionStorage.removeItem('cb_rescues'); } catch(e) {}
          // Spec 40/circuit breaker: in the viewer (no login screen), watch
          // the stream. A dead stream consumes the same per-session budget as
          // login-stuck. Once exhausted, tell the server to quarantine the
          // assignment before bouncing to root; root then serves the queue
          // page rather than redirecting back into the dead viewer.
          if (streamDead()) {
            noMediaT = 0; stillT = 0; lastT = null;
            var rc2 = 0;
            try { rc2 = parseInt(sessionStorage.getItem('cb_rescues') || '0', 10) || 0; } catch(e) {}
            if (rc2 < MAX_RESCUES) {
              try { sessionStorage.setItem('cb_rescues', String(rc2 + 1)); } catch(e) {}
              rescue("stream-dead");
            } else {
              fetch("/fleet/rescue", {method:"POST",
                headers:{"Content-Type":"application/json"},
                body: JSON.stringify({requester:"watchdog", reason:"stream-dead-cap"})})
                .catch(function(){});
            }
            location.href = "/";
          }
        }
      })
      .catch(function(){});
  }, MS);
})();
</script>
"""


def _inject_watchdog(html: str) -> str:
    tag = "</head>"
    js = (_WATCHDOG
          .replace("__RESCUE_AFTER__", str(CB_RESET_AFTER))
          .replace("__MAX_RESCUES__", str(CB_MAX_RESCUES))
          .replace("__RESCUE_COOLDOWN_MS__", str(int(CB_RESET_COOLDOWN_S * 1000)))
          .replace("__STREAM_AFTER__", str(CB_STREAM_AFTER)))
    if tag in html:
        return html.replace(tag, js + tag, 1)
    return js + html


# --- GrantHub /connect page (spec 47 GH.5) -------------------------------
def _connect_page(email: str) -> str:
    """GrantHub page — SSO-gated (Remote-Email = who you are).

    Red/green states (spec 34 §3, never a false green):
      • Not Shared (red): the vault key hasn't been captured. Instructions:
        open Secrets (the vault) in the slot browser and unlock it — the
        grant is captured automatically the moment the vault unlocks.
      • Shared (green): the vault key is wrapped and stored; the broker can
        read your vault items. Revoke button → confirm popup → POST
        /connect/revoke → back to Not Shared (revocation bites: unwrap
        fails, re-mint dies).
    Polls /connect/status every 2 s; the top bar pill follows the same
    state on every surface (queue, landing, session)."""
    e = html.escape(email)
    s = html.escape(SECRETS_URL, quote=True)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>GrantHub: {e}</title>
{_FAVICON_LINK}
<style>
:root{{color-scheme:dark}}
body{{background:#0f1115;color:#e6e8ee;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:48px 20px;box-sizing:border-box}}
.card{{background:#181b22;border:1px solid #2a2e39;border-radius:12px;max-width:620px;width:100%;padding:32px}}
h1{{font-size:20px;margin:0 0 6px}}
.sub{{color:#9aa1af;font-size:13px;margin-bottom:24px}}
.pill{{display:inline-flex;align-items:center;gap:8px;font-size:14px;font-weight:600;padding:6px 14px;border-radius:999px;margin-bottom:20px}}
.pill .dot{{width:9px;height:9px;border-radius:50%;display:inline-block}}
.pill.shared{{background:rgba(34,197,94,.14);color:#4ade80}}
.pill.shared .dot{{background:#22c55e}}
.pill.noshared{{background:rgba(239,68,68,.12);color:#f87171}}
.pill.noshared .dot{{background:#ef4444}}
.body{{color:#c9cdd8;font-size:14px;line-height:1.55}}
.body ol{{padding-left:20px;margin:10px 0}}
.body li{{margin:6px 0}}
.btn{{display:inline-flex;align-items:center;gap:8px;margin-top:20px;padding:9px 18px;border-radius:6px;
font-size:14px;font-weight:600;text-decoration:none;border:none;cursor:pointer}}
.btn.secrets{{background:#334155;color:#e2e8f0}}
.btn.secrets:hover{{background:#42536b}}
.btn.revoke{{background:#7f1d1d;color:#fecaca}}
.btn.revoke:hover{{background:#991b1b}}
.granted{{border-left:3px solid #22c55e;padding:8px 14px;background:rgba(34,197,94,.07);border-radius:0 6px 6px 0;margin-top:16px;font-size:13px}}
.err{{color:#f87171;font-size:13px;margin-top:12px;display:none}}
.foot{{margin-top:26px;color:#6b7280;font-size:12px}}
</style></head>
<body>
<div class="card">
  <h1>GrantHub</h1>
  <div class="sub">{e}</div>
  <div id="pill" class="pill noshared"><span class="dot"></span><span id="pillLabel">Checking…</span></div>
  <div id="bodyNoshared" class="body">
    <p>Your vault key is <b>not shared</b> with the broker yet. Granting takes one unlock:</p>
    <ol>
      <li>Click <b>Open the PMO City vault</b> below (or the top-bar <b>🔒 Secrets</b> pill) — it opens the <b>Vaultwarden vault in a new tab</b> inside this CloudBrowser window.</li>
      <li>Unlock it with your master password.</li>
      <li>Return to this tab — the grant is captured <b>automatically</b> and this page turns green.</li>
    </ol>
    <button class="btn secrets" id="openSecretsBtn">🔒 Open the PMO City vault</button>
  </div>
  <div id="bodyShared" class="body" style="display:none">
    <p>Your vault key is <b>shared</b> with the broker. It is wrapped (AES-256-GCM) with a
    per-user key that only your browser profile folder can unwrap — the master password
    is never stored.</p>
    <div id="grantedAt" class="granted"></div>
    <button class="btn revoke" id="revokeBtn">✕ Revoke grant</button>
    <div id="err" class="err"></div>
  </div>
  <div class="foot">The <b>🔗 Shared</b> pill in the top bar reflects this same state on every page.</div>
</div>
<script>
(function(){{
  var e = document.getElementById.bind(document);
  function paint(j){{
    var shared = !!(j && j.ok && j.usable);
    e('pill').className = 'pill ' + (shared ? 'shared' : 'noshared');
    e('pillLabel').textContent = shared ? '🔗 Shared' : '🔗 Not Shared';
    e('bodyNoshared').style.display = shared ? 'none' : '';
    e('bodyShared').style.display = shared ? '' : 'none';
    if (shared && j.granted_at) {{
      e('grantedAt').textContent = 'Granted ' + j.granted_at.replace('T',' ').replace('Z',' UTC');
    }}
  }}
  function poll(){{
    fetch('/connect/status', {{cache:'no-store'}})
      .then(function(r){{return r.json();}})
      .then(paint)
      .catch(function(){{ e('pillLabel').textContent = 'unreachable'; }});
  }}
  poll(); setInterval(poll, 2000);
  // Spec 48: Open Secrets drives the KIOSK (POST /kiosk/open → slot
  // restart-api), never a dead-end desktop tab — works from the kiosk
  // AND from a legacy desktop /connect tab.
  e('openSecretsBtn').addEventListener('click', function(){{
    var b = this;
    if (b.disabled) return;
    b.disabled = true; b.textContent = '🔒 Opening the vault…';
    fetch('/kiosk/open?url=' + encodeURIComponent('{s}'), {{method:'POST'}})
      .then(function(r){{ if (!r.ok) throw new Error('HTTP ' + r.status); }})
      .then(function(){{ b.disabled = false; b.textContent = '🔒 Open the PMO City vault'; }})
      .catch(function(){{ b.disabled = false; b.textContent = '🔒 Open the PMO City vault';
        e('err').style.display = ''; e('err').textContent =
          'Your session ended — take a slot again, then open the vault from this page.'; }});
  }});
  e('revokeBtn').addEventListener('click', function(){{
    if (!confirm('Revoke the broker\\'s access to your vault key?\\nUnlocking again in Secrets will re-grant.')) return;
    fetch('/connect/revoke', {{method:'POST'}})
      .then(function(r){{return r.json();}})
      .then(paint)
      .catch(function(){{ e('err').style.display=''; e('err').textContent='Revoke failed — try again.'; }});
  }});
}})();
</script>
</body></html>
"""


# --- State ---------------------------------------------------------------
_state = {}
_lock = threading.Lock()
_save_lock = threading.Lock()  # serialize STATE_FILE writers
_pushed = {}
_offer_holds = {}  # slot index (int) → email, while a queue offer is pending
_expiring = {}  # email → slot index being expired by the reaper (release reason)
_expiring_since = {}  # email → when the reaper first started expiring it
_quarantined = {}  # email → slot index whose rescue budget was exhausted
_quarantine_reason = {}  # email → terminal failure reason for diagnostics


def load_state():
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
    except Exception:
        st = {"users": {}, "slots": {}, "archives": {}}
    st.setdefault("users", {})
    st.setdefault("slots", {})
    st.setdefault("archives", {})
    st.setdefault("queue", [])     # spec 31 entries
    st.setdefault("sessions", {})  # email → {slot, started_at, tier}
    st.setdefault("history", {})   # tier → [durations s] (adaptive ETA)
    st.setdefault("queue_seq", 0)  # persisted id sequence (spec 36 §19)
    st.setdefault("queue_timeouts", {})  # terminal agent queue timeout ids
    st.setdefault("rescue_at", {})  # email → last rescue ts (spec 39)
    # Heal duplicate queue ids: a legacy in-memory counter reset on every
    # restart, so fresh entries reused ids of entries that survived in the
    # persisted queue — the live fleet had TWO 'q-1' entries and _eta_for's
    # id lookup handed both users position 1. Renumber by enqueue order
    # only when duplicates exist (renumbering always would break agent
    # pollers holding a valid id across a restart).
    _q = st["queue"]
    if len({e.get("id") for e in _q}) != len(_q):
        for i, e in enumerate(sorted(_q, key=lambda e: e.get("enqueued_at", 0)), 1):
            e["id"] = f"q-{i:x}"
        st["queue_seq"] = max(st["queue_seq"], len(_q))
    else:
        _m = 0
        for e in _q:
            s = str(e.get("id", ""))
            if s.startswith("q-"):
                try:
                    _m = max(_m, int(s[2:], 16))
                except ValueError:
                    pass
        st["queue_seq"] = max(st["queue_seq"], _m)
    # Backward compat: legacy archives were plain floats (idle, resumable).
    for u, v in list(st["archives"].items()):
        if not isinstance(v, dict):
            st["archives"][u] = {"at": v if isinstance(v, (int, float)) else time.time(),
                                 "reason": "idle"}
    if not st["slots"]:
        for email, k in list(st["users"].items()):
            st["slots"][str(k)] = email
    return st


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with _save_lock:
            with open(tmp, "w") as f:
                json.dump(st, f)
            os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"[router] state save failed: {e}", flush=True)


def _median(vals):
    if not vals:
        return None
    s = sorted(vals)[-50:]
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _tier_of_slot(k):
    return "agent" if k in _AGENT_KS else "human"


def _eta_for(entry, st):
    """Position (1-based, type-aware) and ETA in seconds (spec 31 §12 Q1).

    ETA is TIME-BASED, not a static statistical constant (Tigo 2026-08-22:
    "waiting time is always fixed at 26min"). The active sessions' remaining
    time — started_at + max_session − now — counts down on every poll, so
    the queue page's displayed wait decreases as the active session
    approaches its end. Positions beyond the busy slots add one median
    session length per pipeline step: each freed slot immediately takes a
    new occupant who runs ~med before freeing it again."""
    tier = entry["type"]
    same = [e for e in st["queue"]
            if e["type"] == tier and e["status"] in ("waiting", "offered")]
    order = sorted(same, key=lambda e: (-e.get("priority", 0), e["enqueued_at"]))
    pos = next((i + 1 for i, e in enumerate(order)
                if e is entry or (e["id"] == entry["id"] and
                                  e["email"] == entry.get("email"))), None)
    if pos is None:
        if entry.get("status") == "backed_off":
            # Backed-off entries are deliberately not in the active queue
            # ordering. Their position is not meaningful while hidden.
            return None, 0
        return None, 0
    med = _median(st.get("history", {}).get(tier, []))
    if med is None:  # cold start
        med = MAX_SESSION_S[tier] / 2.0
    # Cap at the CURRENT session limit: history keeps durations from older
    # higher limits (e.g. 30-min era after CB_HUMAN_MAX_SESSION_MIN was cut
    # to 15) and would otherwise inflate every pipeline step.
    med = min(med, MAX_SESSION_S[tier])
    now = time.time()
    # Slot-free pipeline: session u frees its slot at started_at + MAX, and
    # every `med` seconds after that (each new occupant runs ~med).
    rems = []
    for u, s in st["sessions"].items():
        if s.get("tier") != tier:
            continue
        rem = s.get("started_at", now) + MAX_SESSION_S[tier] - now
        # Expiring sessions release after the reaper grace (teardown).
        if u in _expiring:
            grace = max(2 * CB_REAPER_INTERVAL_S, 10.0)
            rem = max(rem, _expiring_since.get(u, now) + grace - now)
        rems.append(max(rem, 0.0))
    rems.sort()
    busy = len(rems)
    if pos <= busy:
        # the pos-th slot to free serves this entry
        eta = rems[pos - 1]
    else:
        # all busy slots free once, then the queue drains in `med` steps.
        # busy=0: the free slot takes the head NOW, so the wait for entry
        # at pos is (pos-1) steps — the user's OWN future session is not
        # part of the wait to OPEN (spec 36 §26: pos 2 showed 2×med).
        q, m = divmod(pos - busy - 1, max(busy, 1))
        eta = (rems[m] + (q + 1) * med) if busy else (pos - 1) * med
    return pos, max(int(eta), CB_QUEUE_POLL_INTERVAL_S)


def _expire_agent_entry_locked(entry, now):
    """Move one expired waiting agent to the terminal timeout index.

    Caller must hold ``_lock``.  This is shared by the reaper and the GET
    polling path so a deadline is enforced even when a reaper tick is late.
    """
    if entry.get("type") != "agent" or entry.get("status") != "waiting":
        return False
    eid = entry["id"]
    email = entry["email"]
    _offer_holds.pop(entry.get("slot"), None)
    _state["queue"].remove(entry)
    timeouts = _state.setdefault("queue_timeouts", {})
    timeouts[eid] = now
    if len(timeouts) > 256:
        for old_id in sorted(timeouts, key=lambda q: timeouts[q])[:-256]:
            timeouts.pop(old_id, None)
    _state["archives"][email] = {"at": now, "reason": "queue_timeout"}
    return True


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cb-router/3"

    # ---- helpers -------------------------------------------------------
    def _email(self):
        vals = self.headers.get_all("Remote-Email") or []
        return (vals[-1] if vals else self.headers.get("Remote-Email", "")).strip()

    def _log(self, msg):
        # Request paths may carry the internal Neko auto-login password in
        # query parameters. Keep operational logs path-only.
        path = urllib.parse.urlsplit(self.path).path or "/"
        print(f"[router] {self.command} {path} user={self._email() or '-'} {msg}", flush=True)

    def _bearer(self):
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.startswith("Bearer ") else ""

    def _broker_identity(self, require_owner=True):
        """Audit B3/B4 — server-derived broker identity from the bearer.

        Returns (slot_k, owner, email) where owner is the CURRENT owner of
        the calling slot per router state and email is the request's
        Remote-Email. Enforces: the bearer must be a configured per-slot
        token (or the legacy shared token when no per-slot tokens are
        configured), the slot must be owned, and the supplied Remote-Email
        MUST equal the server-derived owner — any mismatch is rejected
        (returns 403 payload) so no slot can claim another user's
        identity. When require_owner=False only the token validity is
        checked (email-less operations)."""
        bearer = self._bearer()
        if not bearer:
            return (403, None, None, None), {"ok": False,
                                             "error": "broker token required"}
        k = _slot_for_bearer(bearer)
        if k is None:
            if not CB_GRANTHUB_BROKER_TOKEN or \
                    bearer != CB_GRANTHUB_BROKER_TOKEN:
                return (403, None, None, None), {"ok": False,
                                                 "error": "forbidden"}
            k = 0  # legacy shared token: owner must come from the email
        email = self._email()
        owner = _slot_owner(k) if k else (email or "").lower()
        if require_owner:
            if not owner:
                return (403, None, None, None), \
                    {"ok": False, "error": "slot has no owner"}
            if not email or email.lower() != owner:
                return (403, None, None, None), \
                    {"ok": False, "error": "slot owner mismatch"}
        return (200, k, owner, email), None

    def _resolve(self):
        """Return (slot_index or None, woke: bool). Order: live sticky →
        IDLE archive wake (spec 29) → auto-create. ONLY reason=idle archives
        auto-wake (walk-away resume). Spec 41 (2026-08-22, Tigo): expired /
        released / offer_expired archives NEVER wake — they re-queue FIFO,
        so the Exit button cannot let the releaser cut the queue; the freed
        slot goes to the queue head."""
        global _state
        with _lock:
            email = self._email()
            if email in _state["users"]:
                # A capped rescue is terminal for this assignment. The
                # watchdog may have returned to root before the slot callback
                # finished; never route that user back into the same viewer.
                if email in _quarantined:
                    return None, False
                return _state["users"][email], False
            arc = _state["archives"].get(email)
            if arc and arc.get("reason") == "idle":
                for k in _HUMAN_KS:
                    if str(k) not in _state["slots"] and k not in _offer_holds:
                        _state["users"][email] = k
                        _state["slots"][str(k)] = email
                        _state["sessions"][email] = {
                            "slot": k, "started_at": time.time(), "tier": "human"}
                        _state["rescue_at"].pop(email, None)  # spec 54
                        _state["archives"].pop(email, None)
                        save_state(_state)
                        print(f"[router] archive wake {email} → slot-{k}",
                              flush=True)
                        return k, True
                return None, False  # no free slot — queue page instead
            if arc and arc.get("reason") == "expired":
                return None, False  # must re-queue (queue page enqueues)
            # Circuit breaker (2026-08-28): a QUARANTINE reason is terminal
            # for this assignment — stream_dead_cap / rescue_cap must NEVER
            # auto-assign. The rescue-cap quarantine already tore the
            # assignment down; without this guard _resolve()'s auto-create
            # instantly re-assigns the broken user to the freed slot (no
            # human action, same wedged viewer). They surface a waiting/
            # recovery state and can only re-enter by explicitly taking a
            # fresh offer. released/offer_expired keep the spec-41 FIFO
            # semantics: they fall through to the FIFO guard below and may
            # auto-create ONLY when no human is queued.
            if arc and arc.get("reason") in ("stream_dead_cap", "rescue_cap"):
                return None, False  # quarantine — recovery/waiting only
            if not AUTO_CREATE:
                return None, False
            # Spec 41 FIFO: while any human entry waits/offered, a free slot
            # belongs to the QUEUE HEAD (the reaper offers it), never to a
            # newcomer/auto-create — otherwise a released user could cut the
            # queue in the window before the reaper's offer tick.
            if any(e.get("type") == "human"
                   and e.get("status") in ("waiting", "offered")
                   for e in _state["queue"]):
                return None, False
            for k in _HUMAN_KS:
                if str(k) not in _state["slots"] and k not in _offer_holds:
                    _state["users"][email] = k
                    _state["slots"][str(k)] = email
                    _state["sessions"][email] = {
                        "slot": k, "started_at": time.time(), "tier": "human"}
                    _state["rescue_at"].pop(email, None)  # spec 54
                    save_state(_state)
                    print(f"[router] assigned {email} → slot-{k}", flush=True)
                    return k, True
            return None, False

    def _wake_slot(self, k, email):
        """Synchronous wake: restore archive + start chrome on slot k."""
        api_port = SLOT_API_CONTAINER_PORT
        try:
            req = urllib.request.Request(
                f"http://slot-{k}:{api_port}/wake", method="POST",
                data=json.dumps({"user": email}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status == 200
        except Exception as e:
            print(f"[router] wake slot-{k} failed: {e}", flush=True)
            return False

    def _slot_health(self, k):
        """Read restart-api health for readiness reconciliation."""
        api_port = SLOT_API_CONTAINER_PORT
        try:
            req = urllib.request.Request(
                f"http://slot-{k}:{api_port}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode() or "{}")
        except Exception as e:
            print(f"[router] slot-{k} readiness probe failed: {e}",
                  flush=True)
            return None

    @staticmethod
    def _slot_ready_from_health(obj, email):
        programs = obj.get("programs") or {}
        chrome = str(programs.get("google-chrome", "")).upper()
        return (obj.get("ok") is not False
                and obj.get("suspended") is False
                and obj.get("cdp_ok") is True
                and chrome.startswith("RUNNING")
                and obj.get("user") == email)

    def _ensure_slot_ready(self, k, email):
        """Ensure an assigned slot has owner-bound, usable Chrome."""
        obj = self._slot_health(k)
        if not isinstance(obj, dict):
            return False
        if self._slot_ready_from_health(obj, email):
            return True
        owner = obj.get("user")
        suspended = bool(obj.get("suspended"))
        chrome = str((obj.get("programs") or {}).get(
            "google-chrome", "")).upper()
        if not suspended and owner not in (None, email):
            print(f"[router] slot-{k} readiness owner mismatch: "
                  f"expected={email} actual={owner}", flush=True)
            return False
        if suspended or chrome.startswith("STOPPED"):
            if not self._wake_slot(k, email):
                return False
        deadline = time.time() + 60
        while time.time() < deadline:
            obj = self._slot_health(k)
            if isinstance(obj, dict) and self._slot_ready_from_health(obj, email):
                return True
            if isinstance(obj, dict) and obj.get("suspended") is False:
                owner = obj.get("user")
                if owner not in (None, email):
                    print(f"[router] slot-{k} readiness owner changed: "
                          f"expected={email} actual={owner}", flush=True)
                    return False
            time.sleep(0.5)
        print(f"[router] slot-{k} readiness timeout for {email}", flush=True)
        return False

    def _rollback_unready_assignment(self, email, k):
        """Remove an assignment that did not reach owner-bound readiness."""
        with _lock:
            if _state["users"].get(email) != k:
                return
            _state["users"].pop(email, None)
            _state["slots"].pop(str(k), None)
            _state["sessions"].pop(email, None)
            _state["archives"][email] = {
                "at": time.time(), "reason": "idle"}
            save_state(_state)

    def _waiting_status(self, email):
        """Return the normal caller-keyed waiting payload after rollback."""
        with _lock:
            waiting = [e for e in _state["queue"]
                       if e.get("type") == "human"
                       and e.get("status") == "waiting"]
            pos = next((i + 1 for i, e in enumerate(waiting)
                        if e.get("email") == email), None)
        return {"status": "waiting", "position": pos,
                "waiting": [{"email": e.get("email"), "pos": i + 1}
                             for i, e in enumerate(waiting)],
                "active_humans": [], "agent_count": 0}

    def _slot_clean(self, k: int) -> bool:
        """Spec 45: is slot k genuinely free of a live foreign Chrome?

        The router's take path trusts that the reaper suspended the slot —
        but a stale-suspend no-op (restart-api Hole 1) can leave Chrome
        running for the previous user while the router believes the slot is
        free. Ask the slot's restart-api /health (reports suspended + owner)
        instead of trusting our own state. True = safe to grant.
        """
        try:
            api_port = SLOT_API_CONTAINER_PORT
            req = urllib.request.Request(
                f"http://slot-{k}:{api_port}/health", method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                obj = json.loads(r.read().decode() or "{}")
            suspended = bool(obj.get("suspended"))
            owner = obj.get("user")
            if not suspended:
                print(f"[router] slot-{k} NOT clean: suspended={suspended} "
                      f"owner={owner}", flush=True)
            return suspended
        except Exception as e:
            print(f"[router] slot-{k} health check failed: {e} — treating "
                  f"as NOT clean", flush=True)
            return False

    def _release(self, body):
        """POST /fleet/release — slot reaper suspended its user.
        reason=idle → resumable archive (spec 29); reason=expired (set by the
        router's own reaper via _expiring) → must re-queue (spec 31).
        Spec 32: the slot may pass an explicit reason — the Exit button
        reaches restart-api /release, which suspends the slot and notifies
        with reason=released (user-initiated release → archive).
        Spec 41 (2026-08-22, Tigo): released archives NEVER auto-wake
        (_resolve), so the releaser re-queues FIFO and the freed slot goes
        to the queue head."""
        global _state
        user = (body.get("user") or "").strip().lower()
        if not user:
            return 400, {"ok": False, "error": "user required"}
        with _lock:
            k = _state["users"].pop(user, None)
            had_assignment = k is not None
            had_offer = any(e.get("email") == user and
                            e.get("status") == "offered"
                            for e in _state["queue"])
            if k is not None:
                _state["slots"].pop(str(k), None)
                ses = _state["sessions"].pop(user, None)
                if ses:
                    dur = max(time.time() - ses["started_at"], 0.1)
                    hist = _state["history"].setdefault(ses["tier"], [])
                    hist.append(dur)
                    _state["history"][ses["tier"]] = hist[-50:]
                # Spec 41: a freed slot must be re-identified on its NEXT
                # assignment. The stale _pushed[k] guard otherwise skips
                # _identify_slot after Exit → auto-create re-entry, the slot
                # never learns the (same) user again, and the NEXT Exit's
                # /release notify arrives user-less (restart-api slot_user()
                # was wiped by the previous release) → router 400 → the Exit
                # button silently breaks on the second session.
                _pushed.pop(k, None)
            # Spec 31 fix: a released user's queue entry (granted from the
            # queue) is over — drop it so no stale "active" entry lingers
            # and pollutes queueDepth / blocks the slot accounting.
            _state["queue"] = [e for e in _state["queue"]
                               if e["email"] != user]
            # Spec 31 fix (offer-hold leak): the released user may hold a
            # pending OFFER (slot reserved in offer_holds but never taken
            # — e.g. the slot idle watchdog fired while the user was still
            # 'offered'). Clear those holds, otherwise the reaper's
            # per-slot guard (k in _offer_holds) refuses to offer the slot
            # and the whole queue strands behind a phantom hold.
            for hk, hv in list(_offer_holds.items()):
                if hv == user:
                    _offer_holds.pop(hk, None)
            reason = body.get("reason") or (
                _quarantine_reason.get(user) if user in _quarantined else
                ("expired" if user in _expiring else "idle"))
            if user in _quarantined:
                reason = _quarantine_reason.get(user, reason)
            _expiring.pop(user, None)
            _expiring_since.pop(user, None)
            _quarantined.pop(user, None)
            _quarantine_reason.pop(user, None)
            # Spec 32 fix: a STALE notify (user already released — e.g. the
            # router's self-heal force-release fired while the slot still
            # carries a stale .slot-user.json) must not overwrite the
            # archive's existing reason (expired → re-queue semantics).
            # k is None here, so only write when no archive exists yet.
            _guard = had_assignment or had_offer or user not in _state["archives"]
            if _guard:
                _state["archives"][user] = {"at": time.time(), "reason": reason}
            save_state(_state)
        print(f"[router] released {user} (was slot {k}) → archived "
              f"reason={reason}", flush=True)
        return 200, {"ok": True, "user": user, "released_slot": k,
                     "reason": reason}

    def _quarantine_suspend(self, email, k):
        """Teardown the assignment after the rescue circuit opens.

        The slot is authoritative for profile/download cleanup and calls
        /fleet/release when done. This helper never mutates another user's
        assignment; a concurrent release or a late callback is harmless.
        """
        try:
            req = urllib.request.Request(
                f"http://slot-{k}:9230/suspend", method="POST",
                data=json.dumps({"reason": _quarantine_reason.get(
                    email, "rescue_cap")}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200:
                    raise OSError(f"status {r.status}")
            # The slot normally calls /fleet/release after teardown. If it
            # returns successfully without a callback (legacy/ownerless slot
            # or a transient callback failure), converge the router state here
            # rather than leaving a quarantined assignment active forever.
            with _lock:
                still_owned = _state["users"].get(email) == k
            if still_owned:
                code, obj = self._release({
                    "user": email,
                    "reason": _quarantine_reason.get(email, "rescue_cap")})
                if code != 200:
                    raise OSError(obj.get("error", "router release failed"))
        except Exception as e:
            print(f"[router] quarantine suspend slot-{k} for {email} "
                  f"failed: {e}", flush=True)
            # Keep _expiring as the retry/self-heal latch. The reaper will
            # retry the suspend and force-release if the callback never lands.

    def _session_release(self, email):
        """Spec 65 (2026-08-25): user-clicked Exit in the client-page top
        bar. The slot owns the teardown (restart-api /release does the
        snapshot → archive → wipe and notifies back with
        reason=released); here we only verify the active session and
        forward to the owner's slot, so a release can never target a
        different user's slot (same trust shape as _wake_slot). The
        router state pops via the slot's existing notify."""
        with _lock:
            k = _state["users"].get(email)
        if k is None:
            return 400, {"ok": False, "error": "no active session"}
        try:
            req = urllib.request.Request(
                f"http://slot-{k}:9230/release", method="POST",
                data=b"{}", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                ok = r.status == 200
            if not ok:
                return 502, {"ok": False,
                             "error": f"slot-{k} release failed (HTTP {r.status})"}
        except Exception as e:
            print(f"[router] /session/release slot-{k} unreachable: {e}",
                  flush=True)
            return 502, {"ok": False, "error": "slot unreachable"}
        print(f"[router] user release {email} → slot-{k} /release forwarded",
              flush=True)
        return 200, {"ok": True}

    def _fleet_status(self):
        global _state
        with _lock:
            q = _state["queue"]
            return {"ok": True,
                    "users": dict(_state["users"]),
                    "slots": dict(_state["slots"]),
                    "archives": {u: v.get("reason") for u, v in _state["archives"].items()},
                    "queueDepth": {
                        "human": len([e for e in q if e["type"] == "human"
                                      and e["status"] in ("waiting", "offered")]),
                        "agent": len([e for e in q if e["type"] == "agent"
                                      and e["status"] in ("waiting", "offered")])},
                    "sessions": {u: {k2: v2 for k2, v2 in s.items() if k2 != "started_at"}
                                 for u, s in _state["sessions"].items()},
                    "queue": [{k2: e.get(k2) for k2 in
                               ("id", "type", "email", "status", "slot",
                                "enqueued_at")} for e in q],
                    "autoCreate": AUTO_CREATE, "nSlots": N_SLOTS,
                    "rescues": dict(_state["rescue_at"]),
                    "cb": {"humanSlots": CB_HUMAN_SLOTS, "agentSlots": CB_AGENT_SLOTS}}

    def _target(self, k):
        """Return (host, port, path) for slot k — port chosen by Host header."""
        hostname = self.headers.get("Host", "").split(":")[0].lower()
        port = FILES_PORT if hostname.startswith("cloudfiles") else SLOT_PORT
        return f"slot-{k}", port, self.path

    # ---- queue engine (human view + agent API) --------------------------
    # Return the queue entry object (not its id) so callers can compute
    # position against the exact occurrence, including legacy duplicate IDs.
    def _enqueue_human(self, email):
        """Add a human queue entry unless one is already waiting/offered.
        Returns the entry id."""
        with _queue_lock:
            with _lock:
                for e in _state["queue"]:
                    if e["type"] == "human" and e["email"] == email and \
                            e["status"] in ("waiting", "offered"):
                        return e["id"]
                eid = _next_eid()
                _state["queue"].append({
                    "id": eid, "type": "human", "email": email,
                    "priority": 1 if email in CB_ADMIN_EMAILS else 0,
                    "enqueued_at": time.time(), "status": "waiting",
                    "offer_expires_at": None})
                save_state(_state)
                print(f"[router] queued human {email} ({eid})", flush=True)
                return eid

    def _human_status(self, email):
        """JSON for the queue page poll — keyed by the SSO email."""
        global _state
        entry = None
        with _lock:
            entry = next((e for e in _state["queue"]
                          if e["type"] == "human" and e["email"] == email
                          and e["status"] in ("waiting", "offered", "active")), None)
            if entry is None:
                # A backed-off record is only a fallback when this user has no
                # newer waiting/offered/active entry. Re-enqueue can leave the
                # old cooldown row beside the current row; selecting it first
                # hides a live offer and suppresses Open Browser.
                entry = next((e for e in _state["queue"]
                              if e["type"] == "human" and e["email"] == email
                              and e["status"] == "backed_off"), None)
        if entry is None:
            # Not queued: is a slot free for them right now?
            k, woke = self._resolve()
            if k is not None:
                if woke:
                    if not self._ensure_slot_ready(k, email):
                        self._rollback_unready_assignment(email, k)
                        self._enqueue_human(email)
                        return self._waiting_status(email)
                elif not self._ensure_slot_ready(k, email):
                    self._rollback_unready_assignment(email, k)
                    self._enqueue_human(email)
                    return self._waiting_status(email)
                # Spec 65: active users WITHOUT a queue entry (auto-create /
                # archive-wake path — the common case) must still get the
                # session-remaining countdown; the title-proxy top-bar
                # timer hides without session_ttl_s.
                with _lock:
                    ses = _state["sessions"].get(email, {})
                    started = ses.get("started_at") or time.time()
                    ttl = max(0, int(started + MAX_SESSION_S[ses.get(
                        "tier", "human")] - time.time()))
                return {"status": "active",
                        "open_url": self._open_url(email),
                        "session_ttl_s": ttl}
            self._enqueue_human(email)
            with _lock:
                entry = next((e for e in _state["queue"]
                              if e["type"] == "human"
                              and e["email"] == email), None)
        if entry is None:
            return {"status": "unknown", "position": None, "eta_s": 0,
                    "waiting": [], "active_humans": [], "agent_count": 0}
        with _lock:
            pos, eta = _eta_for(entry, _state)
        humans = []
        # Numbered queue list (Tigo 2026-08-22): the viewer's own email
        # is ALWAYS listed here with its position — no longer "top bar
        # only". Other users' emails are listed only when
        # CB_QUEUE_SHOW_EMAILS is set.
        for e in sorted([x for x in _state["queue"]
                         if x["type"] == "human"
                         and x["status"] in ("waiting", "offered")],
                        key=lambda x: (-x.get("priority", 0), x["enqueued_at"])):
            if e["email"] == email or CB_QUEUE_SHOW_EMAILS:
                p, _ = _eta_for(e, _state)
                humans.append({"email": e["email"], "pos": p})
        agents = len([e for e in _state["queue"] if e["type"] == "agent"
                      and e["status"] in ("waiting", "offered")])
        out = {"status": entry["status"], "position": pos, "eta_s": eta,
               "waiting": humans,
               "active_humans": [e for e in sorted(_state["users"])
                                 if e != email],
               "agent_count": agents,
               "queue_id": entry["id"]}
        # Offered users get the Open Browser button too — with the offer
        # countdown so they know the one-shot chance is ticking
        # (spec 36 §21: grace, then back of the queue).
        if entry["status"] in ("active", "offered"):
            # Spec 48 rev2 (Tigo 2026-08-23): queue-page pills are plain
            # main-browser links — no pending-goto intent anymore. The
            # entry opens a bare new tab; the landing Shared pill's
            # ?goto= (if any) rides the explicit entry link only.
            out["open_url"] = self._open_url(email)
            if entry["status"] == "offered":
                out["offer_ttl_s"] = max(
                    0, int(entry.get("offer_expires_at", 0) - time.time()))
            else:
                # Active viewers see a session-remaining countdown in
                # the position slot (was a meaningless "?" — Tigo
                # 2026-08-22 screenshot).
                s = _state["sessions"].get(email, {})
                started = s.get("started_at") or time.time()
                out["session_ttl_s"] = max(
                    0, int(started + MAX_SESSION_S[entry["type"]]
                           - time.time()))
        elif entry["status"] == "backed_off":
            # Spec 77: a user repeatedly ignoring offers is hidden from the
            # offer scan until cooldown.
            out["backoff_ttl_s"] = max(
                0, int(entry.get("backed_off_until", 0) - time.time()))
        return out

    def _open_url(self, email, goto=None):
        pwd = urllib.parse.quote(NEKO_PASSWORD, safe="")
        usr = urllib.parse.quote(email, safe="")
        if goto:
            return (f"/?pwd={pwd}&usr={usr}"
                    f"&goto={urllib.parse.quote(goto, safe='')}")
        return f"/?pwd={pwd}&usr={usr}"

    # --- Spec 48: kiosk-open (capture-surface UX) -------------------------
    def _kiosk_open_slot(self, k, url):
        """POST a slot's restart-api /open-url: open `url` as a kiosk tab
        (live) or queue it as the pending start URL (Chrome still down)."""
        try:
            req = urllib.request.Request(
                f"http://slot-{k}:9230/open-url",
                data=json.dumps({"url": url}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
            self._log(f"kiosk-open slot-{k}: {url}")
            return True
        except Exception as e:
            print(f"[router] kiosk-open slot-{k} {url}: {e}", flush=True)
            return False

    def _kiosk_open(self, email, url):
        """POST /kiosk/open — session-page pills drive the kiosk Chrome.

        Only users with an active slot can target the kiosk; the URL must
        be a whitelisted surface. Runs the slot call synchronously (the
        server is threaded; the viewer fetch waits for the verdict)."""
        with _lock:
            k = _state["users"].get(email)
        if k is None:
            return 409, {"ok": False, "error": "no active slot"}
        ok_url = _whitelisted_surface(url)
        if ok_url is None:
            return 400, {"ok": False, "error": "url not allowed"}
        # Spec 50 (2026-08-23, Tigo report): the slot opens this URL via
        # Chrome's /json/new, which CANNOT resolve a relative path (no
        # base origin) — GH.8's relative GRANTHUB_URL (/connect) made the
        # GrantHub pill open a BLANK tab. Resolve same-origin surfaces
        # against the public origin the request came in on (Host +
        # X-Forwarded-Proto); the kiosk then reaches /connect through
        # Caddy/tinyauth exactly like the user's main browser.
        if ok_url.startswith("/") and not ok_url.startswith("//"):
            host = (self.headers.get("Host") or
                    "cloudbrowser.dev01.pmo.city").split(":")[0]
            proto = self.headers.get("X-Forwarded-Proto") or "https"
            ok_url = f"{proto}://{host}{ok_url}"
        if self._kiosk_open_slot(k, ok_url):
            return 200, {"ok": True, "slot": k}
        return 502, {"ok": False, "error": "slot unreachable"}

    def _agent_enqueue(self, body):
        """POST /queue — agent API (spec 31 §8). Bearer token required."""
        if not CB_AGENT_TOKEN:
            return 501, {"error": "agent_queue_disabled",
                         "detail": "CB_AGENT_TOKEN unset"}
        if self._bearer() != CB_AGENT_TOKEN:
            return 401, {"error": "unauthorized"}
        email = (body.get("caller") or "agent").strip().lower()
        with _queue_lock:
            with _lock:
                # Fast path: free agent slot right now?
                for k in _AGENT_KS:
                    if str(k) not in _state["slots"]:
                        eid = _next_eid()
                        _state["users"][email] = k
                        _state["slots"][str(k)] = email
                        _state["sessions"][email] = {
                            "slot": k, "started_at": time.time(), "tier": "agent"}
                        _state["rescue_at"].pop(email, None)  # spec 54
                        _state["queue"].append({
                            "id": eid, "type": "agent", "email": email,
                            "priority": 0, "enqueued_at": time.time(),
                            "status": "active", "offer_expires_at": None})
                        save_state(_state)
                        print(f"[router] agent {email} → slot-{k} (instant)",
                              flush=True)
                        return 200, {"queue_id": eid, "position": 0, "eta_s": 0,
                                     "status": "active", "slot": k}
                eid = _next_eid()
                _state["queue"].append({
                    "id": eid, "type": "agent", "email": email, "priority": 0,
                    "enqueued_at": time.time(), "status": "waiting",
                    "offer_expires_at": None})
                save_state(_state)
                pos, eta = _eta_for(_state["queue"][-1], _state)
                print(f"[router] queued agent {email} ({eid})", flush=True)
                return 202, {"queue_id": eid, "position": pos, "eta_s": eta,
                             "status": "waiting"}

    def _agent_status(self, eid):
        """GET /queue/<id> with hard agent queue-timeout enforcement."""
        with _lock:
            entry = next((e for e in _state["queue"] if e["id"] == eid), None)
            if entry is None:
                timed_out = _state.get("queue_timeouts", {}).get(eid)
                if timed_out is not None:
                    return 200, {"queue_id": eid, "status": "timeout",
                                 "position": None, "eta_s": 0}
                return 404, {"error": "not_found"}
            # A GET immediately after the deadline must not expose stale
            # waiting state if the reaper has not reached this row yet.
            if (entry.get("type") == "agent" and
                    entry.get("status") == "waiting" and
                    time.time() - entry.get("enqueued_at", time.time()) >=
                    CB_AGENT_QUEUE_TIMEOUT_S):
                _expire_agent_entry_locked(entry, time.time())
                save_state(_state)
                return 200, {"queue_id": eid, "status": "timeout",
                             "position": None, "eta_s": 0}
            pos, eta = _eta_for(entry, _state)
            out = {"queue_id": eid, "status": entry["status"],
                   "position": pos, "eta_s": eta}
            if entry["status"] == "active":
                out["slot"] = entry.get("slot")
            return 200, out

    def _agent_leave(self, eid):
        global _state
        with _lock:
            entry = next((e for e in _state["queue"] if e["id"] == eid), None)
            if entry is None:
                return 404, {"error": "not_found"}
            # Release a pending offer hold BEFORE marking left — otherwise a
            # slot stays phantom-held (offer_holds never cleared by the
            # grace sweep, which only demotes status=="offered") and the
            # whole queue strands (incident 2026-08-23: DELETE /queue/<id>
            # stranded the human queue after the reaper had offered the
            # entry; Tigo's queue page never flipped to the button).
            k0 = entry.get("slot")
            if k0 is not None:
                _offer_holds.pop(k0, None)
            entry["status"] = "left"
            entry.pop("slot", None)
            entry["offer_expires_at"] = None
            if entry["email"] in _state["users"]:
                k = _state["users"].pop(entry["email"], None)
                if k is not None:
                    _state["slots"].pop(str(k), None)
                _state["sessions"].pop(entry["email"], None)
            save_state(_state)
            return 200, {"ok": True}

    # ---- raw TCP proxy (HTTP + WS) -------------------------------------
    def _pipe(self, src, dst, until_closed=True):
        """Pump bytes between two sockets until either closes."""
        try:
            while True:
                r, _, _ = select.select([src, dst], [], [], 30)
                for s in r:
                    data = s.recv(65536)
                    if not data:
                        return
                    try:
                        (dst if s is src else src).sendall(data)
                    except Exception:
                        return
        except Exception:
            pass
        finally:
            try:
                src.close()
            except Exception:
                pass
            try:
                dst.close()
            except Exception:
                pass

    def _pipe_injected(self, conn, up, max_buf=16 * 1024 * 1024):
        """Pipe upstream → client, injecting the session watchdog into any
        text/html response (fallback path: the primary index fetch failed,
        so the watchdog was never injected). Non-HTML streams through
        unchanged. When HTML is too large to buffer, flush it un-injected
        — a working page beats a watchdog (the extension-hosted watchdog
        covers that case anyway)."""
        buf = b""
        while True:
            chunk = up.recv(65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > max_buf:
                conn.sendall(buf)
                while True:
                    c = up.recv(65536)
                    if not c:
                        break
                    conn.sendall(c)
                return
        head, _, body = buf.partition(b"\r\n\r\n")
        ctype = ""
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-type:"):
                ctype = line.split(b":", 1)[1].strip().lower().decode("latin1", "replace")
                break
        if "text/html" in ctype:
            html = body.decode("utf-8", "replace")
            body = _inject_watchdog(html).encode("utf-8", "replace")
            # We read the full body (Connection: close upstream), so
            # normalise framing: drop any transfer-encoding/chunked
            # framing and send one authoritative Content-Length.
            head = _re.sub(rb"(?im)^transfer-encoding:.*\r\n", b"", head)
            head = _re.sub(rb"(?im)^content-length:.*\r\n", b"", head)
            head += b"\r\nContent-Length: " + str(len(body)).encode()
        out = head + b"\r\n\r\n" + body
        conn.sendall(out)

    def _proxy_raw(self, host, port, path, inject_html=False):
        """Forward the raw request (as received) to upstream, then pump."""
        try:
            up = socket.create_connection((host, port), timeout=10)
        except Exception as e:
            self._log(f"connect {host}:{port} failed: {e}")
            try:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(b"bad gateway")
            except Exception:
                pass
            return

        req_line = f"{self.command} {path} {self.request_version}\r\n"
        is_ws = self.headers.get("Upgrade", "").lower() == "websocket"
        try:
            up.sendall(req_line.encode())
            if is_ws:
                for h, v in self.headers.items():
                    up.sendall(f"{h}: {v}\r\n".encode())
            else:
                for h, v in self.headers.items():
                    if h.lower() in ("connection", "proxy-connection"):
                        continue
                    up.sendall(f"{h}: {v}\r\n".encode())
                up.sendall(b"Connection: close\r\n")
            up.sendall(b"\r\n")
            if self.command in ("POST", "PUT", "PATCH", "DELETE"):
                ln = int(self.headers.get("Content-Length", "0") or 0)
                if ln:
                    remaining = ln
                    while remaining > 0:
                        chunk = self.rfile.read(min(65536, remaining))
                        if not chunk:
                            break
                        up.sendall(chunk)
                        remaining -= len(chunk)
        except Exception as e:
            self._log(f"forward failed: {e}")
            up.close()
            return

        if inject_html:
            try:
                self._pipe_injected(self.connection, up)
            except Exception as e:
                self._log(f"injected pipe failed: {e}")
                try:
                    up.close()
                except Exception:
                    pass
        else:
            self._pipe(self.connection, up)
        if not is_ws:
            self.close_connection = True

    # ---- handlers ------------------------------------------------------
    def _route(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        # Slot-side grant retrieval and refresh-rotation persistence are
        # authenticated by the per-slot bearer and deliberately carry no
        # Remote-Email. Dispatch both before the external SSO email gate;
        # each handler derives the owner server-side.
        if (self.path == "/connect/grant/material"
                and self.command == "GET"):
            self._granthub_material()
            return
        if (self.path == "/connect/grant" and self.command == "POST"
                and not self._email()):
            self._granthub_grant(None)
            return
        # GrantHub admin kill switch (GH.6): Bearer-only, no Remote-Email —
        # must be dispatched BEFORE the email gate.
        if self.path == "/connect/admin/revoke-all" and self.command == "POST":
            self._granthub_admin()
            return
        email = self._email()
        if not email:
            # Internal control endpoints (no Remote-Email): /fleet/* only.
            if self.path.startswith("/fleet") and self.command == "POST":
                self._fleet_post()
                return
            if self.path == "/fleet/status":
                self._json(200, self._fleet_status())
                return
            if self.path.startswith("/queue") and self.command in ("GET", "POST", "DELETE"):
                self._agent_api()
                return
            self._log("no Remote-Email")
            self.send_response(401)
            self.end_headers()
            return

        # Spec 39/40: wedged-neko rescue — the page watchdog carries
        # Remote-Email. Dispatch BEFORE any human-entry/enqueue logic, so a
        # wedged session can't be turned into a queue/landing page.
        # reason: login-stuck (spec 39) | stream-dead (spec 40).
        if self.path == "/fleet/rescue" and self.command == "POST":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n)) if n else {}
            except Exception:
                body = {}
            code, obj = self._rescue(
                email, reason=str(body.get("reason") or "login-stuck"))
            self._json(code, obj)
            return

        # Spec 65 (2026-08-25): user-initiated release from the neko
        # CLIENT page top bar (title-proxy injected button). Same trust
        # shape as /fleet/rescue: Remote-Email identifies the active user
        # (tinyauth-appended). The slot owns the teardown (restart-api
        # /release → snapshot → archive → wipe → notify reason=released);
        # this endpoint verifies the session and forwards to the owner's
        # slot, so a release can never target a different user.
        if self.path == "/session/release" and self.command == "POST":
            code, obj = self._session_release(email)
            self._json(code, obj)
            return

        # GrantHub (spec 47): /connect page + grant API run in-process —
        # dispatch before the host/path-based slot proxy fallthrough.
        if self.path == "/connect" or self.path.startswith("/connect/"):
            self._granthub()
            return

        # Spec 73 (D2): OTP code-exchange (chat-ask leg) — broker requests,
        # agent submits the user's code, broker fetches once. Same trust
        # shape as /connect/grant (Remote-Email + Bearer, fail closed).
        # Audit B10: challenge-bound one-shot requests. NOTE: match the
        # PATH WITHOUT the query string (pending carries ?challenge=).
        _p = urllib.parse.urlparse(self.path)
        _op = _p.path
        if _op == "/otp/challenge" and self.command == "POST":
            self._otp_challenge(email)
            return
        if _op == "/otp/cancel" and self.command == "POST":
            self._otp_cancel(email)
            return
        if _op == "/otp/request" and self.command == "POST":
            self._otp_request(email)
            return
        if _op == "/otp/pending" and self.command == "GET":
            self._otp_pending_get(email)
            return
        if _op == "/otp/submit" and self.command == "POST":
            self._otp_submit(email)
            return

        # Spec 48: session-page pills drive the kiosk Chrome. POST
        # /kiosk/open?url=<surface> — resolves the user's active slot and
        # asks its restart-api to open a whitelisted surface as a KIOSK tab
        # (never a new desktop tab). Requires Remote-Email (above).
        # NOTE: self.path carries the query string — compare parsed path.
        _p = urllib.parse.urlparse(self.path)
        if _p.path == "/kiosk/open" and self.command == "POST":
            url = urllib.parse.parse_qs(_p.query).get("url", [""])[0]
            code, obj = self._kiosk_open(email, url)
            self._json(code, obj)
            return

        # Human browser entry: root of the cloudbrowser host (no pwd param
        # present) → landing page (slot free) or queue page (no slot).
        hostname = self.headers.get("Host", "").split(":")[0].lower()
        qs = urllib.parse.urlparse(self.path).query
        is_root = urllib.parse.urlparse(self.path).path in ("/", "/index.html")
        if hostname.startswith("cloudbrowser") and is_root and "pwd=" not in qs:
            # Grace window (reaper tearing the slot down): serve the queue
            # page, not the landing page — the user's session is over.
            if email in _expiring or email in _quarantined:
                self._enqueue_human(email)
                self._log("QUEUE (expiring/quarantined) → queue page")
                self._html(200, _queue_page(email))
                return
            with _lock:
                already_active = email in _state["users"]
            k, woke = self._resolve()
            if k is None:
                self._enqueue_human(email)
                self._log("QUEUE (no slot) → queue page")
                self._html(200, _queue_page(email))
                return
            # Active-session reload (neko strips ?pwd/usr from the URL after
            # auto-login, so a plain reload of "/" lands here): jump straight
            # back into the live session — no "Open Browser" landing detour
            # (Tigo 2026-08-22). Only when the session was already active
            # BEFORE _resolve(): archive-wake/auto-create still need the
            # landing page (wake barrier while Chrome comes up).
            if already_active:
                # A persisted assignment is not necessarily a usable browser:
                # the slot can have been idle-suspended or Chrome can have
                # died after the router state was written. Reconcile readiness
                # before redirecting this reload into the session.
                if not self._ensure_slot_ready(k, email):
                    with _lock:
                        _state["users"].pop(email, None)
                        _state["slots"].pop(str(k), None)
                        _state["sessions"].pop(email, None)
                        _state["archives"][email] = {
                            "at": time.time(), "reason": "idle"}
                        save_state(_state)
                    self._enqueue_human(email)
                    self._log("QUEUE (active assignment not ready) → queue page")
                    self._html(503, _queue_page(email))
                    return
                self.send_response(302)
                self.send_header("Location", self._open_url(email))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                self._log("active reload → 302 into session")
                return
            if not self._ensure_slot_ready(k, email):
                with _lock:
                    _state["users"].pop(email, None)
                    _state["slots"].pop(str(k), None)
                    _state["sessions"].pop(email, None)
                    _state["archives"][email] = {
                        "at": time.time(), "reason": "idle"}
                    save_state(_state)
                self._enqueue_human(email)
                self._log("QUEUE (fresh assignment not ready) → queue page")
                self._html(503, _queue_page(email))
                return
            if _pushed.get(k) != email:
                _pushed[k] = email
                threading.Thread(target=_identify_slot,
                                 args=(k, email), daemon=True).start()
            self._log("slot ready → landing page")
            self._html(200, _landing_page(email))
            return

        # /queue/status — human queue page poll (keyed by SSO email).
        if hostname.startswith("cloudbrowser") and self.path == "/queue/status":
            self._json(200, self._human_status(email))
            return

        # /fleet/my-status — read-only per-user state probe for the session
        # watchdog injected into the neko page. NEVER transitions state
        # (unlike /queue/status which assigns/wakes/enqueues).
        if hostname.startswith("cloudbrowser") and self.path == "/fleet/my-status":
            with _lock:
                if email in _quarantined:
                    st = "recovery"  # terminal rescue failure; never active
                elif email in _expiring:
                    st = "expired"  # grace window: slot being torn down
                elif email in _state["users"]:
                    st = "active"
                else:
                    qe = next((e for e in _state["queue"]
                               if e["type"] == "human" and e["email"] == email
                               and e["status"] in ("waiting", "offered", "active")),
                              None)
                    if qe is not None:
                        st = "active" if qe["status"] == "active" else "queued"
                    elif email in _state["archives"]:
                        st = _state["archives"][email].get("reason", "idle")
                    else:
                        st = "new"
            self._json(200, {"email": email, "state": st})
            return

        # CloudFiles host → per-slot downloads surface WITHOUT slot
        # acquisition (spec 37 §2.5 LOCKED: no queue — always accessible,
        # no session limit, no reaper). Route to the user's assigned slot
        # when they have one (their downloads live there), else the human
        # slot — never enqueue, never wake, never show the queue page.
        if hostname.startswith("cloudfiles"):
            k = None
            with _lock:
                k = _state["users"].get(email)
            if k is None:
                k = 1
            host, port, path = self._target(k)
            self._log(f"CF → {host}:{port}{path}")
            self._proxy_raw(host, port, path)
            return

        # neko entry: root WITH pwd/usr params (Open Browser click) → serve
        # the slot's index with the session watchdog injected, so the neko
        # login screen can never take over when the session ends.
        if hostname.startswith("cloudbrowser") and is_root and "pwd=" in qs:
            now = time.time()
            # Spec 48: ?goto=<surface> on the entry — landing-page pills
            # ("enter the kiosk at the target URL"). Whitelisted, then
            # forwarded to the slot's restart-api after the wake below.
            # (Queue-page pending-goto removed 2026-08-23: CloudFiles +
            # Secrets are plain main-browser links now — only the landing
            # Shared pill carries ?goto=.)
            goto_url = _whitelisted_surface(
                urllib.parse.parse_qs(qs).get("goto", [""])[0])
            # Offer take / expiry (spec 36 §21): when a slot freed, the
            # reaper OFFERED it to the queue head (status 'offered',
            # offer_holds reserves the slot, session clock NOT started yet).
            # Clicking Open Browser within the grace takes it — the clock
            # starts NOW, at take-over. An expired offer sends the user to
            # the BACK of the queue (one-shot chance).
            entry = None
            offered_slot = None
            offer_valid = False
            with _lock:
                entry = next((e for e in _state["queue"]
                              if e["type"] == "human" and e["email"] == email),
                             None)
                if entry is not None and entry["status"] == "offered":
                    if (entry.get("offer_expires_at", 0) > now
                            and _offer_holds.get(entry.get("slot")) == email):
                        offer_valid = True
                        offered_slot = entry["slot"]
                    else:
                        _expire_offer_locked(entry, now)
                        save_state(_state)
                        print(f"[router] offer expired for {email} — "
                              f"back of queue", flush=True)
                elif entry is not None and entry["status"] == "backed_off":
                    self._html(200, _queue_page(email))
                    return
            if offer_valid:
                k = offered_slot
                # Spec 45 (isolation): before granting a taken offer, verify
                # the slot actually reports suspended (Chrome not running).
                # A stale-suspend no-op (Hole 1) would otherwise hand the new
                # user the previous user's LIVE Chrome. If the slot is not
                # clean, refuse the take and keep the queue entry offered —
                # the reaper will re-offer once the slot is genuinely free.
                if not self._slot_clean(k):
                    print(f"[router] take REFUSED slot-{k} for {email}: slot "
                          f"not clean (chrome running?) — keeping offered",
                          flush=True)
                    self._html(200, _queue_page(email))
                    return
                with _lock:
                    _state["users"][email] = k
                    _state["slots"][str(k)] = email
                    _state["sessions"][email] = {
                        "slot": k, "started_at": now, "tier": "human"}
                    _state["rescue_at"].pop(email, None)  # spec 54
                    entry["status"] = "active"
                    entry["offer_expires_at"] = None
                    entry.pop("slot", None)
                    # Spec 77: a successful take resets the per-(email, slot)
                    # offer-expiry counter — same user can rebuild trust.
                    entry.pop("offer_expiries", None)
                    entry.pop("backed_off_until", None)
                    _offer_holds.pop(k, None)
                    _state["archives"].pop(email, None)
                    save_state(_state)
                print(f"[router] offer taken by {email} → slot-{k}",
                      flush=True)
                # Spec 46 (latent spec-42 bug): the offer-take MUST wake the
                # slot. spec 42 removed the offer-time pre-wake (wake storm)
                # and the comment said "the take path wakes it" — but the take
                # path never did (woke=False and the wake block below only
                # lives in the _resolve() branch), so an offer-take handed the
                # user a SUSPENDED slot: neko UI but no Chrome. _slot_clean()
                # above already proved the slot is genuinely suspended (no
                # live foreign Chrome), so waking here is safe and correct —
                # restore the new owner's archive + start Chrome. On wake
                # failure, roll the grant back (re-archive, reaper re-offers).
                if not self._wake_slot(k, email):
                    with _lock:
                        _state["users"].pop(email, None)
                        _state["slots"].pop(str(k), None)
                        _state["sessions"].pop(email, None)
                        _state["archives"][email] = {
                            "at": now, "reason": "idle"}
                        save_state(_state)
                    print(f"[router] wake failed for {email} — re-archived",
                          flush=True)
            else:
                k, woke = self._resolve()
                if k is None:
                    self._enqueue_human(email)
                    self._log("QUEUE (no slot) → queue page")
                    self._html(200, _queue_page(email))
                    return
                # Browser entry: refresh the start clock ONLY when it is
                # stale — a persisted started_at surviving a redeploy (state
                # file carries the pre-deploy session) must never trigger
                # instant reaper expiry, and a future timestamp (clock skew)
                # must not stall the reaper. A healthy in-flight clock is
                # KEPT, so a reload cannot reset the session limit and push
                # every queued user's ETA back up (Tigo 2026-08-22).
                with _lock:
                    ses = _state["sessions"].get(email)
                    if ses is not None:
                        _el = now - ses["started_at"]
                        if (_el > MAX_SESSION_S[ses.get("tier", "human")]
                                or _el < -60):
                            ses["started_at"] = now
                            save_state(_state)  # persist — survives redeploys
                            print(f"[router] stale session clock refreshed "
                                  f"for {email} ({_el:.0f}s old)", flush=True)
                if woke and not self._wake_slot(k, email):
                    with _lock:
                        _state["users"].pop(email, None)
                        _state["slots"].pop(str(k), None)
                        _state["sessions"].pop(email, None)
                        _state["archives"][email] = {
                            "at": now, "reason": "idle"}
                        save_state(_state)
                    print(f"[router] wake failed for {email} — re-archived",
                          flush=True)
            if _pushed.get(k) != email:
                _pushed[k] = email
                threading.Thread(target=_identify_slot,
                                 args=(k, email), daemon=True).start()
            # Spec 48: landing-page ?goto= — ask the slot to open the target
            # surface as a kiosk tab (now, or as the pending start URL if
            # Chrome is still coming up). Fire-and-forget; never delays the
            # index response.
            if goto_url:
                threading.Thread(target=self._kiosk_open_slot,
                                 args=(k, goto_url), daemon=True).start()
            host, port, _ = self._target(k)
            self._log(f"→ {host}:{port}/ (neko index + watchdog)")
            # Spec 51/55: the slot's title-proxy can respawn right after a
            # wake (supervisord stops it on idle/archive, starts on wake),
            # so the first index fetches can hit Connection refused. Spec 55
            # (2026-08-24, Tigo): a single 0.8s retry was NOT enough — the
            # client got a broken/refused page during the startup window and
            # its WS retry is weak, so it sat at "connecting" forever.
            # Retry in a bounded loop until the slot's title-proxy answers,
            # then serve. If it never comes up, fall back to the raw proxy
            # (which injects the watchdog) so the page still loads.
            idx = None
            idx_err = None
            for _attempt in range(8):
                try:
                    req = urllib.request.Request(
                        f"http://{host}:{port}/",
                        headers={"Remote-Email": email})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        idx = r.read().decode("utf-8", "replace")
                    break
                except Exception as e:
                    idx_err = e
                    time.sleep(0.5)
            if idx is None:
                self._log(f"index fetch failed ({idx_err}) — raw proxy "
                          f"fallback (watchdog injected for text/html)")
                self._proxy_raw(host, port, "/", inject_html=True)
                return
            body = _inject_watchdog(idx).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        k, woke = self._resolve()
        if k is None:
            # Any other path while fully busy (shouldn't happen for browsers,
            # but keep a sane fallback): queue page.
            self._enqueue_human(email)
            self._html(200, _queue_page(email))
            return
        if woke and not self._wake_slot(k, email):
            with _lock:
                _state["users"].pop(email, None)
                _state["slots"].pop(str(k), None)
                _state["sessions"].pop(email, None)
                _state["archives"][email] = {"at": time.time(), "reason": "idle"}
                save_state(_state)
            print(f"[router] wake failed for {email} — re-archived",
                  flush=True)
        if _pushed.get(k) != email:
            _pushed[k] = email
            threading.Thread(target=_identify_slot,
                             args=(k, email), daemon=True).start()
        host, port, path = self._target(k)
        self._log(f"→ {host}:{port}{path}")
        self._proxy_raw(host, port, path)

    def _agent_api(self):
        """Agent queue endpoints (headerless — Bearer token, spec 31 §8)."""
        p = urllib.parse.urlparse(self.path)
        if self.command == "POST" and p.path == "/queue":
            n = int(self.headers.get("Content-Length") or 0)
            body = {}
            if n:
                try:
                    body = json.loads(self.rfile.read(n))
                except Exception:
                    body = {}
            code, obj = self._agent_enqueue(body)
            self._json(code, obj)
            return
        if self.command == "GET" and p.path.startswith("/queue/"):
            eid = p.path[len("/queue/"):]
            code, obj = self._agent_status(eid)
            self._json(code, obj)
            return
        if self.command == "DELETE" and p.path.startswith("/queue/"):
            eid = p.path[len("/queue/"):]
            code, obj = self._agent_leave(eid)
            self._json(code, obj)
            return
        self._json(404, {"ok": False, "error": "not found"})

    def _fleet_post(self):
        """Internal control endpoints (headerless — a Remote-Email carrying
        request is a proxied user request, never a control call), plus the
        user-facing /fleet/rescue (spec 39 — the watchdog carries
        Remote-Email)."""
        email = (self.headers.get("Remote-Email") or "").strip().lower()
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            body = {}
        if self.path == "/fleet/rescue":
            # Spec 39/40: wedged-neko rescue, requested by the page
            # watchdog. Must carry Remote-Email (the current active user
            # on a slot). reason = login-stuck (spec 39) | stream-dead
            # (spec 40) — recorded for observability.
            if not email:
                self._json(401, {"ok": False, "error": "Remote-Email required"})
                return
            code, obj = self._rescue(email, reason=str(body.get("reason") or "login-stuck"))
            self._json(code, obj)
            return
        if email:
            self._log("control call rejected (Remote-Email present)")
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/fleet/release":
            code, obj = self._release(body)
            self._json(code, obj)
        else:
            self._json(404, {"ok": False, "error": "not found"})

    # --- GrantHub (spec 47: GH.2 API + GH.5 page + GH.6 kill switch) -----
    def _granthub(self):
        """GrantHub API — identity via Remote-Email (tinyauth-appended).
        In-process (grant store on the sessions volume, GRANT_ROOT):
          GET  /connect        → grant page (user browser)
          GET  /connect/status → {"shared": bool, "granted_at", "revoked"}
          POST /connect/grant  → broker-only (Bearer + Remote-Email):
                                 body {"key": <b64 user key>, "scope": ...}
                                 → AES-GCM wrap + store
          POST /connect/revoke → self-service revoke (own grant)
          POST /connect/admin/revoke-all → Bearer (dispatched pre-email)"""
        email = self._email()
        if not email:
            self._json(401, {"ok": False, "error": "Remote-Email required"})
            return
        p = urllib.parse.urlparse(self.path)
        if self.command == "GET" and p.path == "/connect":
            self._html(200, _connect_page(email))
            return
        if self.command == "GET" and p.path == "/connect/status":
            st = granthub.status(GRANT_ROOT, email)
            self._json(200, {"ok": True, **st})
            return
        if self.command == "POST" and p.path == "/connect/grant":
            self._granthub_grant(email)
            return
        if self.command == "GET" and p.path == "/connect/grant/material":
            # Audit B3: slot-authenticated read of the CURRENT owner's
            # decrypted grant material (slots no longer mount the store).
            self._granthub_material()
            return
        if self.command == "POST" and p.path == "/connect/revoke":
            granthub.revoke(GRANT_ROOT, email)
            st = granthub.status(GRANT_ROOT, email)
            print(f"[router] GrantHub grant revoked for {email}", flush=True)
            self._json(200, {"ok": True, **st})
            return
        self._json(404, {"ok": False, "error": "not found"})

    def _granthub_grant(self, email):
        """POST /connect/grant — broker-only. The slot broker carries the
        slot owner's Remote-Email AND the shared broker token; fail closed
        when CB_GRANTHUB_BROKER_TOKEN is unset. Body (spec 59 — the
        session-token leg): {"key": <b64 user key>, "session": <vault
        refresh token>, "scope": ...}. At least one of key/session is
        required:
          • key (+ optional session) → full grant, freshly wrapped
          • session only → session-leg UPGRADE of an existing grant
        Plaintext never logged; both are AES-GCM-wrapped here. Audit
        B3/B4: the bearer is the slot's OWN per-slot token and the
        identity is server-derived (Remote-Email must equal the slot's
        current owner)."""
        if not _SLOT_TOKENS and not CB_GRANTHUB_BROKER_TOKEN:
            self._json(501, {"ok": False, "error": "broker token not configured"})
            return
        # A per-slot bearer is sufficient and authoritative: derive the owner
        # from router state. Remote-Email is optional for internal slot calls;
        # when supplied, it may only confirm (never override) that owner.
        (code, k, owner, _req_email), err = self._broker_identity(
            require_owner=False)
        if err:
            self._json(code, err)
            return
        if k:
            if not owner:
                self._json(403, {"ok": False, "error": "slot has no owner"})
                return
            if _req_email and _req_email.lower() != owner:
                self._json(403, {"ok": False, "error": "slot owner mismatch"})
                return
            email = owner  # server-derived owner is authoritative
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            body = {}
        key = str(body.get("key") or "")
        session = str(body.get("session") or "")
        if not key and not session:
            self._json(400, {"ok": False, "error": "key or session required"})
            return
        try:
            if key:
                wrapped, k_user = granthub.wrap(key)
                wrapped_session = None
                if session:
                    wrapped_session, _ = granthub.wrap_bytes(session.encode(), k_user)
                granthub.save_grant(GRANT_ROOT, email, wrapped, k_user=k_user,
                                    wrapped_session=wrapped_session,
                                    scope=str(body.get("scope") or granthub.SCOPE_DEFAULT))
                print(f"[router] GrantHub grant stored for {email}"
                      + (" (+session leg)" if wrapped_session else " (no session leg)"),
                      flush=True)
            else:
                # Session-only upgrade of an existing key grant.
                wrapped_session, _ = granthub.wrap_bytes(
                    session.encode(), granthub.load_kuser(GRANT_ROOT, email))
                granthub.add_session(GRANT_ROOT, email, wrapped_session)
                print(f"[router] GrantHub session leg upgraded for {email}",
                      flush=True)
        except granthub.GrantError as e:
            print(f"[router] GrantHub session upgrade failed for {email}: "
                  f"{type(e).__name__}: {e}", flush=True)
            self._json(400, {"ok": False, "error": str(e)})
            return
        except Exception as e:
            print(f"[router] GrantHub wrap failed for {email}: "
                  f"{type(e).__name__}: {e}", flush=True)
            self._json(400, {"ok": False, "error": "wrap failed"})
            return
        st = granthub.status(GRANT_ROOT, email)
        self._json(200, {"ok": True, **st})

    def _granthub_material(self):
        """GET /connect/grant/material — SLOT-ONLY (audit B3: removal of
        shared grant access). Returns the CURRENT owner's decrypted vault
        key + refresh-token session leg ({key, session, scope}) for the
        slot whose per-slot bearer authenticated the call. The identity
        is 100% server-derived — the slot can NEVER ask for another
        user's material. 404 when no grant exists. This endpoint is the
        ONLY way a slot may obtain grant material (slots do not mount
        the grant store anymore)."""
        if not _SLOT_TOKENS:
            self._json(501, {"ok": False, "error": "broker token not configured"})
            return
        (code, _k, owner, _email), err = self._broker_identity(
            require_owner=False)
        if err:
            self._json(code, err)
            return
        # For this slot-only endpoint the per-slot bearer is the complete
        # identity credential: derive the current owner server-side and never
        # require or trust caller-supplied Remote-Email. Legacy shared tokens
        # have no slot identity and therefore remain forbidden here.
        if not _k or not owner:
            self._json(403, {"ok": False, "error": "slot has no owner"})
            return
        # An omitted identity header is the production slot-client shape. If a
        # caller does supply one, it may only confirm—not override—the owner
        # derived from the bearer and router state.
        if _email and _email.lower() != owner:
            self._json(403, {"ok": False, "error": "slot owner mismatch"})
            return
        try:
            key = granthub.unwrap(GRANT_ROOT, owner)
            session = granthub.unwrap_session(GRANT_ROOT, owner)
            g = granthub.load_grant(GRANT_ROOT, owner)
            self._json(200, {"ok": True, "key": key, "session": session,
                             "scope": (g or {}).get("scope",
                                                    granthub.SCOPE_DEFAULT)})
        except granthub.GrantError:
            self._json(404, {"ok": False, "error": "no grant"})

    def _granthub_admin(self):
        """POST /connect/admin/revoke-all — admin kill switch (GH.6).
        Bearer CB_GRANTHUB_ADMIN_TOKEN; fail closed when unset. After this,
        every unwrap fails (keys deleted) — the fleet can re-grant."""
        if not CB_GRANTHUB_ADMIN_TOKEN:
            self._json(501, {"ok": False, "error": "admin token not configured"})
            return
        if self.headers.get("Authorization") != f"Bearer {CB_GRANTHUB_ADMIN_TOKEN}":
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        n = granthub.revoke_all(GRANT_ROOT)
        print(f"[router] GrantHub admin revoke-all: {n} grants revoked", flush=True)
        self._json(200, {"ok": True, "revoked": n})

    # --- Spec 73 (D2) — OTP code-exchange (chat-ask leg) ------------------
    # Audit B10: one-shot challenge-bound requests. A request is keyed by
    # an opaque random id, bound to {slot, owner}; the code may be
    # submitted once and fetched once (atomic consume); replacement,
    # replay, stale ids, cross-slot reads and owner reassignment all fail
    # closed. The legacy email-only flow (below) remains for the shared
    # broker token mode (no per-slot tokens configured).
    def _otp_challenge(self, email):
        """POST /otp/challenge — broker-only, SLOT-BOUND. Creates a
        one-shot code request for the caller's OWN slot owner and returns
        the opaque request id. Remote-Email must equal the slot's current
        owner (server-derived) — a slot can never raise a request for
        another user's MFA."""
        if not _SLOT_TOKENS and not CB_GRANTHUB_BROKER_TOKEN:
            self._json(501, {"ok": False, "error": "broker token not configured"})
            return
        (code, k, owner, _req_email), err = self._broker_identity()
        if err:
            self._json(code, err)
            return
        rid = secrets.token_hex(16)
        with _otp_lock:
            _otp_pending[rid] = {"requested_at": time.time(), "code": None,
                                 "submitted_at": None, "slot": k,
                                 "owner": owner,
                                 "target": str(self.headers.get("X-Target") or "")}
        print(f"[router] OTP challenge {rid[:8]}… armed for {owner}"
              f" (slot {k})", flush=True)
        self._json(200, {"ok": True, "request_id": rid,
                         "ttl_s": int(CB_OTP_TTL_S)})

    def _otp_request(self, email):
        """POST /otp/request — legacy broker-only flow, now SLOT-BOUND
        (audit B4): the bearer must be the caller slot's own token (or
        the shared token when no per-slot tokens are configured) and the
        Remote-Email must equal the slot's current owner. Arms a pending
        one-time-code request. In-memory only."""
        if not _SLOT_TOKENS and not CB_GRANTHUB_BROKER_TOKEN:
            self._json(501, {"ok": False, "error": "broker token not configured"})
            return
        (code, k, owner, _req_email), err = self._broker_identity()
        if err:
            self._json(code, err)
            return
        rid = secrets.token_hex(16)
        with _otp_lock:
            _otp_pending[rid] = {"requested_at": time.time(), "code": None,
                                 "submitted_at": None, "slot": k,
                                 "owner": owner, "target": ""}
        print(f"[router] OTP request armed for {owner} (slot {k})", flush=True)
        self._json(200, {"ok": True, "request_id": rid,
                         "ttl_s": int(CB_OTP_TTL_S)})

    def _otp_cancel(self, email):
        """POST /otp/cancel — broker-only, SLOT-BOUND. Explicitly consumes
        and deletes the challenge (the broker aborted the login). Any
        later submit/fetch for that id fails."""
        if not _SLOT_TOKENS and not CB_GRANTHUB_BROKER_TOKEN:
            self._json(501, {"ok": False, "error": "broker token not configured"})
            return
        (code, k, owner, _req_email), err = self._broker_identity()
        if err:
            self._json(code, err)
            return
        rid = str(self.headers.get("X-Challenge") or "")
        with _otp_lock:
            p = _otp_pending.pop(rid, None)
            if not p or p.get("slot") != k or p.get("owner") != owner:
                self._json(404, {"ok": False, "error": "unknown challenge"})
                return
        print(f"[router] OTP challenge {rid[:8]}… cancelled ({owner})",
              flush=True)
        self._json(200, {"ok": True})

    def _otp_pending_get(self, email):
        """GET /otp/pending — broker-only, SLOT-BOUND, challenge-bound
        (audit B10). ?challenge=<request_id>; returns the submitted code
        at most ONCE (atomically consumed on read); expired/unknown
        challenges return code:null/404. The challenge's slot/owner must
        match the caller's server-derived identity."""
        if not _SLOT_TOKENS and not CB_GRANTHUB_BROKER_TOKEN:
            self._json(501, {"ok": False, "error": "broker token not configured"})
            return
        (code, k, owner, _req_email), err = self._broker_identity()
        if err:
            self._json(code, err)
            return
        rid = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query).get("challenge", [""])[0]
        if not rid:
            self._json(400, {"ok": False, "error": "challenge required"})
            return
        with _otp_lock:
            p = _otp_pending.get(rid)
            if not p or time.time() - p["requested_at"] > CB_OTP_TTL_S:
                _otp_pending.pop(rid, None)
                self._json(404, {"ok": False, "error": "unknown challenge"})
                return
            if p.get("slot") != k or p.get("owner") != owner:
                self._json(403, {"ok": False, "error": "forbidden"})
                return
            c = p.get("code")
            p["code"] = None  # read-once
            ttl = int(CB_OTP_TTL_S - (time.time() - p["requested_at"]))
        self._json(200, {"code": c, "ttl_s": max(ttl, 0)})

    def _otp_submit(self, email):
        """POST /otp/submit — agent-only (CB_OTP_AGENT_TOKEN),
        challenge-bound (audit B10). Body {"code": <digits>,
        "challenge": <request_id>}. Stores the employee's one-time code
        for EXACTLY ONE fetch; duplicate submits, stale ids and replays
        after consume are rejected (409/404). The code is never logged
        and never written to the state file. Legacy fallback (no
        challenge id): the oldest pending request for this email is used
        (kept for the pre-B10 flow; still slot-bound by the broker side)."""
        if not CB_OTP_AGENT_TOKEN:
            self._json(501, {"ok": False, "error": "agent token not configured"})
            return
        if self.headers.get("Authorization") != f"Bearer {CB_OTP_AGENT_TOKEN}":
            self._json(403, {"ok": False, "error": "forbidden"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            body = {}
        code = str(body.get("code") or "").strip()
        rid = str(body.get("challenge") or "").strip()
        if not code or not code.isdigit() or len(code) > 10:
            self._json(400, {"ok": False, "error": "bad code"})
            return
        with _otp_lock:
            if rid:
                p = _otp_pending.get(rid)
            else:
                rid = None
                for _rid, _p in _otp_pending.items():
                    if _p.get("owner") == email and _p.get("code") is None \
                            and _p.get("submitted_at") is None:
                        rid, p = _rid, _p
                        break
                else:
                    p = None
            if not p or time.time() - p["requested_at"] > CB_OTP_TTL_S:
                if rid:
                    _otp_pending.pop(rid, None)
                self._json(404, {"ok": False, "error": "unknown challenge"})
                return
            if p.get("submitted_at") is not None:
                self._json(409, {"ok": False, "error": "already submitted"})
                return
            if p.get("code") is not None:
                self._json(409, {"ok": False, "error": "already consumed"})
                return
            p["code"] = code
            p["submitted_at"] = time.time()
        self._json(200, {"ok": True})

    def _rescue(self, email, reason="login-stuck"):
        """Spec 39/40: wedged-neko rescue. The page watchdog calls this when
        a re-entry auto-login failed (reason=login-stuck — neko wedged,
        LOG IN sticks) or the viewer stream is dead/absent (reason=
        stream-dead — blank-page wedge, spec 40). Route: locate the
        caller's slot, ask its restart-api to `supervisorctl restart neko`
        (app process only — profile + tabs preserved), guarded by a
        server-side cooldown. Escalation ceiling lives in the client
        (2 rescue attempts per episode); containers are never restarted."""
        global _state
        with _lock:
            k = _state["users"].get(email)
            if k is None:
                return 401, {"ok": False, "error": "no active session"}
            last = _state["rescue_at"].get(email, 0)
            if isinstance(last, dict):  # spec 40: {ts, reason}
                last_n = last.get("n", 0)
                last = last.get("ts", 0)
            else:
                last_n = 0
            if time.time() - last < CB_RESET_COOLDOWN_S:
                return 429, {"ok": False, "error": "cooldown"}
            # Spec 54/circuit breaker: the rescue budget is a terminal
            # failure for this assignment. Do not leave the user active: mark
            # the session as expiring, then use the normal slot suspend/release
            # path to archive it and free the slot. The request remains under
            # the lock only long enough to make the transition idempotent.
            if last_n >= CB_MAX_RESCUES:
                should_quarantine = email not in _quarantined
                if should_quarantine:
                    _quarantined[email] = k
                    _quarantine_reason[email] = (
                        "stream_dead_cap" if reason == "stream-dead"
                        else "rescue_cap")
                    _expiring[email] = k
                    _expiring_since[email] = time.time()
                    save_state(_state)
                    print(f"[router] rescue cap reached for {email} "
                          f"(n={last_n}) — quarantining slot-{k}", flush=True)
            else:
                should_quarantine = False
        if last_n >= CB_MAX_RESCUES:
            # Network I/O must happen outside _lock: the slot's suspend
            # endpoint synchronously calls /fleet/release back to this router.
            # Holding the lock here deadlocks the callback and leaves the
            # assignment active despite the quarantine decision.
            if should_quarantine:
                self._quarantine_suspend(email, k)
            return 200, {"ok": True, "user": email,
                         "action": "quarantine", "slot": k}
        try:
            req = urllib.request.Request(
                f"http://slot-{k}:9230/restart-neko", method="POST",
                data=json.dumps({"user": email}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                obj = json.loads(r.read().decode() or "{}")
                if r.status != 200 or not obj.get("ok"):
                    return 502, {"ok": False,
                                 "error": obj.get("error", "slot rescue failed")}
        except Exception as e:
            print(f"[router] rescue slot-{k} for {email} failed: {e}", flush=True)
            return 502, {"ok": False, "error": "slot unreachable"}
        with _lock:
            _state["rescue_at"][email] = {
                "ts": time.time(), "reason": reason, "n": last_n + 1}
            save_state(_state)
        print(f"[router] rescue user={email} slot={k} → restart-neko", flush=True)
        return 200, {"ok": True, "user": email, "action": "restart-neko", "slot": k}

    def _html(self, code, data):
        body = data.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._route()
    def do_POST(self):
        self._route()
    def do_PUT(self):
        self._route()
    def do_PATCH(self):
        self._route()
    def do_DELETE(self):
        self._route()
    def do_HEAD(self):
        self._route()

    def log_message(self, fmt, *args):
        pass


def _identify_slot(k, email):
    """Module-level identify POST (shared by the handler and the sweep)."""
    try:
        req = urllib.request.Request(
            f"http://slot-{k}:9230/identify", method="POST",
            data=json.dumps({"user": email, "slot": k}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status != 200:
                raise OSError(f"status {r.status}")
    except Exception as e:
        print(f"[router] identify slot-{k} failed: {e}", flush=True)


def _sweep_loop():
    """Spec 29b identity re-assert sweep (every SWEEP_INTERVAL).

    Spec 77: poll idle slots for an owner-bound boot hint and dispatch a
    standard wake when the hinted owner is not already live elsewhere.
    The assignment is RECORDED in router state (users/slots/sessions) like
    the take/auto-create path, and the owner check is per-slot FRESH so
    the same owner can never be woken into two slots in one pass (live
    bug 2026-08-28: a stale snapshot woke slot-1 AND slot-2 with the same
    user, and users[] never learned the assignment).
    """
    while True:
        time.sleep(SWEEP_INTERVAL)
        try:
            with _lock:
                items = list(_state["users"].items())
            for email, k in items:
                try:
                    _identify_slot(k, email)
                except Exception as e:
                    print(f"[router] sweep identify slot-{k}: {e}", flush=True)
            for k in _HUMAN_KS + _AGENT_KS:
                if str(k) in _state["slots"] or k in _offer_holds:
                    continue  # slot busy — nothing to recover here
                hint = _slot_pending_owner(k)
                if not hint:
                    continue
                if hint in _boot_hints_seen:
                    continue  # one-shot per owner (this process lifetime)
                with _lock:
                    # Fresh per-slot check: the hint owner must not be
                    # live anywhere nor hold an offer.
                    if hint in _state["users"]:
                        continue
                    if any(v == hint for v in _offer_holds.values()):
                        continue
                    _state["users"][hint] = k
                    _state["slots"][str(k)] = hint
                    _state["sessions"][hint] = {
                        "slot": k, "started_at": time.time(), "tier": "human"}
                    _state["archives"].pop(hint, None)
                    _pushed[k] = hint
                    save_state(_state)
                if _wake_slot_global(k, hint):
                    _boot_hints_seen.add(hint)
                    print(f"[router] boot-hint wake slot-{k} → {hint}",
                          flush=True)
                else:
                    with _lock:
                        _state["users"].pop(hint, None)
                        _state["slots"].pop(str(k), None)
                        _state["sessions"].pop(hint, None)
                        _state["archives"][hint] = {
                            "at": time.time(), "reason": "idle"}
                        _pushed.pop(k, None)
                        save_state(_state)
                    print(f"[router] boot-hint wake slot-{k} FAILED for "
                          f"{hint} — assignment rolled back", flush=True)
        except Exception as e:
            print(f"[router] sweep failed: {e}", flush=True)


def _slot_pending_owner(k):
    """Return a slot's pending archive owner, or None on probe failure."""
    try:
        req = urllib.request.Request(
            f"http://slot-{k}:9230/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            obj = json.loads(r.read().decode() or "{}")
        owner = obj.get("pending_archive_owner")
        return owner if isinstance(owner, str) and owner else None
    except Exception as e:
        print(f"[router] slot-{k} boot-hint probe failed: {e}", flush=True)
        return None


# Spec 77: hint owners the router has already dispatched a boot-hint wake
# for (this process lifetime). A slot whose hint was never consumed (owner
# was live elsewhere) must not re-wake that owner later — e.g. after the
# owner's session on another slot ends, the armed hint would otherwise
# auto-re-open their session against the spec's one-shot semantics.
_boot_hints_seen: set = set()


def _expire_offer_locked(entry, now):
    """Move an expired offer to waiting or backed_off.

    Caller holds _lock. The expiry history is carried by the queue entry,
    so it survives router restarts with the existing state file.
    """
    k = entry.get("slot")
    email = entry["email"]
    _offer_holds.pop(k, None)
    expiries = [x for x in entry.get("offer_expiries", [])
                if x.get("at", 0) >= now - CB_OFFER_BACKOFF_WINDOW_S]
    expiries.append({"slot": k, "at": now})
    entry["offer_expiries"] = expiries
    same_slot = sum(1 for x in expiries if x.get("slot") == k)
    entry["status"] = "waiting"
    entry["enqueued_at"] = now
    entry["offer_expires_at"] = None
    entry.pop("slot", None)
    _state["archives"][email] = {"at": now, "reason": "offer_expired"}
    print(f"[router] offer expired for {email} — back of queue", flush=True)
    if same_slot >= CB_OFFER_BACKOFF_THRESHOLD:
        entry["status"] = "backed_off"
        entry["backed_off_until"] = now + CB_OFFER_BACKOFF_COOLDOWN_S
        print(f"[router] offer BACKED_OFF {email} ({same_slot} expiries)",
              flush=True)


def _purge_backed_off_locked(now):
    """Drop entries whose backoff cooldown elapsed. Caller holds _lock."""
    changed = False
    for entry in list(_state["queue"]):
        if entry.get("status") != "backed_off":
            continue
        if now < entry.get("backed_off_until", 0):
            continue
        email = entry["email"]
        _state["queue"].remove(entry)
        _state["archives"][email] = {
            "at": now, "reason": "offer_backed_off_dropped"}
        changed = True
        print(f"[router] offer BACKED_OFF dropped {email}", flush=True)
    return changed


def _expire_agent_queue_entries(now):
    """Expire waiting agent entries and remove them from active queue state.

    ``queue_timeouts`` is a bounded terminal-result index: it lets a polling
    client observe ``status=timeout`` after the active queue row is removed.
    """
    expired = []
    with _lock:
        for entry in list(_state["queue"]):
            if entry.get("type") != "agent" or entry.get("status") != "waiting":
                continue
            if now - entry.get("enqueued_at", now) < CB_AGENT_QUEUE_TIMEOUT_S:
                continue
            eid = entry["id"]
            if _expire_agent_entry_locked(entry, now):
                expired.append(eid)
        if expired:
            save_state(_state)
    for eid in expired:
        print(f"[router] agent queue timeout {eid}", flush=True)
    return expired


def _reaper_loop():
    """Spec 31 reaper (every CB_REAPER_INTERVAL_S):
    1. max-duration expiry — sessions older than their tier max are
       suspended via slot /suspend (idempotent); the slot's release lands
       with reason=expired → user re-queues on next visit.
    2. queue offer — a freed slot is offered to the type head of the queue
       (admin priority first), wake is fired, entry → active."""
    global _state
    while True:
        time.sleep(CB_REAPER_INTERVAL_S)
        try:
            now = time.time()
            _expire_agent_queue_entries(now)
            # 1. expiry
            with _lock:
                for email, ses in list(_state["sessions"].items()):
                    tier = ses.get("tier", "human")
                    if now - ses["started_at"] > MAX_SESSION_S[tier]:
                        k = ses["slot"]
                        if email not in _expiring:
                            _expiring[email] = k
                            _expiring_since[email] = now
                            print(f"[router] reaper: EXPIRING {email} "
                                  f"(tier={tier} slot={k})", flush=True)
            for email, k in list(_expiring.items()):
                try:
                    req = urllib.request.Request(
                        f"http://slot-{k}:9230/suspend", method="POST",
                        data=b"{}", headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=15) as r:
                        print(f"[router] reaper: suspend slot-{k} → "
                              f"{r.status}", flush=True)
                        if r.status != 200:
                            _expiring.pop(email, None)
                            _expiring_since.pop(email, None)
                except Exception as e:
                    print(f"[router] reaper: suspend slot-{k} failed: {e}",
                          flush=True)
                    _expiring.pop(email, None)  # retry next tick
                    _expiring_since.pop(email, None)
            # 1b. self-heal: a slot whose suspend succeeded but whose release
            # callback never landed (e.g. the slot's _suspended latch is
            # stuck) must not wedge the fleet — force-release the expiring
            # user after a grace period so the slot frees and the queue
            # advances. Idempotent vs. a late slot release (_lock serializes).
            grace = max(2 * CB_REAPER_INTERVAL_S, 10.0)
            with _lock:
                for email in list(_expiring):
                    k = _expiring[email]
                    if email in _state["users"] and \
                       now - _expiring_since.get(email, now) > grace:
                        print(f"[router] reaper: force-release {email} "
                              f"(slot-{k} release not received in "
                              f"{grace:.0f}s)", flush=True)
                        _state["users"].pop(email, None)
                        _state["slots"].pop(str(k), None)
                        ses = _state["sessions"].pop(email, None)
                        if ses:
                            dur = max(now - ses["started_at"], 0.1)
                            hist = _state["history"].setdefault(
                                ses["tier"], [])
                            hist.append(dur)
                            _state["history"][ses["tier"]] = hist[-50:]
                        _pushed.pop(k, None)  # re-identify on next assign
                        _state["queue"] = [e for e in _state["queue"]
                                           if e["email"] != email]
                        _state["archives"][email] = {
                            "at": now,
                            "reason": _quarantine_reason.get(
                                email, "expired") if email in _quarantined
                            else "expired"}
                        _expiring.pop(email, None)
                        _expiring_since.pop(email, None)
                        _quarantined.pop(email, None)
                        _quarantine_reason.pop(email, None)
                        save_state(_state)
            # 1c. offer grace sweep (spec 36 §21): an offered entry whose
            # grace elapsed and was NOT taken goes to the BACK of the queue
            # (one-shot chance); the slot hold is released so the next tick
            # re-offers to the new head.
            # Spec 77 (2026-08-28): repeat expiries for one (email, slot)
            # pair enter a persisted cooldown instead of looping forever.
            with _lock:
                changed = False
                for e in list(_state["queue"]):
                    if e.get("status") != "offered":
                        continue
                    if e["email"] in _state["users"]:
                        continue  # taken (defensive — take clears status)
                    if e.get("offer_expires_at", 0) > now:
                        continue  # still within grace
                    _expire_offer_locked(e, now)
                    changed = True
                if _purge_backed_off_locked(now):
                    changed = True
                if changed:
                    save_state(_state)

            # 2. queue offer: a freed slot is OFFERED to the type head of
            # the queue (admin priority first): entry → 'offered' with an
            # expiry (CB_OFFER_GRACE_S), the slot reserved in offer_holds,
            # wake fired so chrome is warm. The user is NOT assigned and the
            # session clock does NOT start until they click Open Browser
            # (take-over). If they never do, the grace sweep (1c) puts them
            # at the back of the queue and the next tick re-offers.
            # Spec 46: NEVER offer a slot that is not genuinely suspended.
            # A dirty freed slot (stale Chrome from a force-release or a
            # release-without-teardown) would be refused at every take and
            # wedge forever — instead self-heal it here: re-suspend, and
            # offer only once /health reports clean. Network calls are done
            # OUTSIDE the lock so the router never blocks on a slot.
            offers = []
            with _lock:
                for k in _HUMAN_KS + _AGENT_KS:
                    if str(k) in _state["slots"] or k in _offer_holds:
                        continue
                    tier = _tier_of_slot(k)
                    # One outstanding offer per tier: a pending offer (or an
                    # orphaned one surviving a restart) must settle first,
                    # otherwise two users could be offered the same slot.
                    if any(e["type"] == tier and e["status"] == "offered"
                           for e in _state["queue"]):
                        continue
                    cand = [e for e in _state["queue"]
                            if e["type"] == tier
                            and e["status"] == "waiting"]
                    if not cand:
                        continue
                    cand.sort(key=lambda e: (-e.get("priority", 0),
                                             e["enqueued_at"]))
                    offers.append((k, cand[0]))
            for k, entry in offers:
                if not _slot_clean_global(k):
                    _suspend_slot_global(k)  # converge to clean next tick
                    continue
                with _lock:
                    # Re-verify under the lock: the slot or entry may have
                    # moved while we were checking health.
                    if str(k) in _state["slots"] or k in _offer_holds:
                        continue
                    if entry.get("status") != "waiting":
                        continue
                    if any(e["type"] == entry["type"]
                           and e["status"] == "offered"
                           for e in _state["queue"]):
                        continue
                    email = entry["email"]
                    entry["status"] = "offered"
                    entry["offer_expires_at"] = now + CB_OFFER_GRACE_S
                    entry["slot"] = k
                    _offer_holds[k] = email
                    save_state(_state)
                    print(f"[router] offer {email} → slot-{k} "
                          f"(tier={entry['type']}, grace {CB_OFFER_GRACE_S:.0f}s)",
                          flush=True)
                    # Spec 42 (incident 41): NO pre-wake at offer time.
                    # The slot stays suspended until the offer is TAKEN —
                    # the take path wakes it. Pre-waking caused a wake
                    # storm (offer/expire every 60 s) that swapped user
                    # profiles under a live Chrome.
        except Exception as e:
            print(f"[router] reaper failed: {e}", flush=True)


def _offer_wake(k, email):
    """Fire the wake for an offered queue entry; on failure release the
    slot hold so the next reaper tick can re-offer (to the same head)."""
    global _state
    if not _wake_slot_global(k, email):
        print(f"[router] offer wake slot-{k} for {email} FAILED — releasing",
              flush=True)
        with _lock:
            _offer_holds.pop(k, None)
            for e in _state["queue"]:
                if e["email"] == email and e["type"] == _tier_of_slot(k) \
                        and e["status"] == "offered":
                    e["status"] = "waiting"
                    e["offer_expires_at"] = None
                    e.pop("slot", None)
                    break
            save_state(_state)
    else:
        with _lock:
            _pushed[k] = email


def _wake_slot_global(k, email):
    try:
        req = urllib.request.Request(
            f"http://slot-{k}:9230/wake", method="POST",
            data=json.dumps({"user": email}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status == 200
    except Exception as e:
        print(f"[router] wake slot-{k} failed: {e}", flush=True)
        return False


def _slot_clean_global(k):
    """Spec 45/46: is slot k genuinely free of a live foreign Chrome?

    Mirrors Router._slot_clean for use from the reaper loop. True = safe to
    offer (slot's restart-api /health reports suspended — Chrome stopped)."""
    try:
        req = urllib.request.Request(
            f"http://slot-{k}:9230/health", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            obj = json.loads(r.read().decode() or "{}")
        suspended = bool(obj.get("suspended"))
        owner = obj.get("user")
        if not suspended:
            print(f"[router] slot-{k} NOT clean: suspended={suspended} "
                  f"owner={owner}", flush=True)
        return suspended
    except Exception as e:
        print(f"[router] slot-{k} health check failed: {e} — treating "
              f"as NOT clean", flush=True)
        return False


def _suspend_slot_global(k):
    """POST the slot's restart-api /suspend. Spec 46 self-heal: with the
    spec-45 restart-api fix a /suspend on a slot whose Chrome is still
    running now force-tears-down and reports suspended, so a dirty freed
    slot converges to clean instead of wedging the fleet."""
    try:
        req = urllib.request.Request(
            f"http://slot-{k}:9230/suspend", method="POST",
            data=b"{}", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = r.status == 200
            print(f"[router] self-heal suspend slot-{k} → {r.status}",
                  flush=True)
            return ok
    except Exception as e:
        print(f"[router] self-heal suspend slot-{k} failed: {e}", flush=True)
        return False


def main():
    global _state
    _state = load_state()
    # Boot hygiene: purge stickiness/sessions for slots outside the active
    # pools (e.g. a slot-2 assignment left over from a pre-spec-31 deploy
    # when CB_AGENT_SLOTS was 0) — those users go back to the queue/archive.
    pool_ks = set(_HUMAN_KS + _AGENT_KS)
    with _lock:
        for email, k in list(_state["users"].items()):
            if k not in pool_ks:
                _state["users"].pop(email, None)
                _state["slots"].pop(str(k), None)
                _state["sessions"].pop(email, None)
                _state["archives"].setdefault(email, {"at": time.time(), "reason": "idle"})
        for s in list(_state["slots"].keys()):
            if int(s) not in pool_ks:
                _state["slots"].pop(s, None)
        # Spec 31 fix: stale "active" queue entries whose grant is gone
        # (user released/archived) must not linger — drop them.
        for e in list(_state["queue"]):
            if e["status"] == "active" \
                    and e["email"] not in _state["users"]:
                _state["queue"].remove(e)
                print(f"[router] boot: dropped stale queue entry {e['id']} "
                      f"({e['email']}, active)", flush=True)
        # Spec 48 incident (2026-08-23): "left" entries (DELETE /queue/<id>)
        # keep their slot/offer residue forever — the grace sweep only
        # demotes status=="offered", so a left entry that was offered holds
        # its slot in _offer_holds after restart and strands the queue.
        # Purge ALL left entries at boot and drop stale slot keys.
        for e in list(_state["queue"]):
            if e.get("status") == "left":
                _state["queue"].remove(e)
                print(f"[router] boot: purged left queue entry {e['id']} "
                      f"({e['email']})", flush=True)
        for k0 in list(_offer_holds.keys()):
            if k0 not in pool_ks:
                _offer_holds.pop(k0, None)
        # Spec 36 §21: offers surviving a restart. Still within grace →
        # restore the hold so the user can take it; expired → apply the same
        # Spec 77 expiry/backoff transition as the live reaper.
        for e in list(_state["queue"]):
            if e.get("status") != "offered":
                continue
            if e.get("offer_expires_at", 0) > time.time():
                _offer_holds[e["slot"]] = e["email"]
                print(f"[router] boot: restored pending offer {e['id']} "
                      f"({e['email']}) → slot-{e['slot']}", flush=True)
            else:
                _expire_offer_locked(e, time.time())
                print(f"[router] boot: expired offer {e['id']} "
                      f"({e['email']}) → back of queue", flush=True)
        _purge_backed_off_locked(time.time())
        save_state(_state)
    port = int(os.environ.get("ROUTER_PORT", "8081"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Proxy)
    threading.Thread(target=_sweep_loop, daemon=True).start()
    threading.Thread(target=_reaper_loop, daemon=True).start()
    print(f"[router] v3 on :{port}, N_SLOTS={N_SLOTS} "
          f"auto_create={AUTO_CREATE} state={STATE_FILE} "
          f"sweep={SWEEP_INTERVAL}s reaper={CB_REAPER_INTERVAL_S}s", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
