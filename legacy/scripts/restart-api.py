#!/usr/bin/env python3
"""W2 restart-api — HTTP restart button + CDP watchdog (D4) + tab persistence (D5).

Tiny stdlib HTTP server inside the viewer container (supervisord program,
port 9230, bound to 0.0.0.0 — reachable by the agent over pmoc-lan at
<viewer-ip>:9230; NOT exposed via traefik).

Endpoints:
  GET  /health      -> JSON: {ok, programs:{name:state}, cdp_ok}
  GET  /config      -> JSON: {ok, homeUrl, tabLimit}  (tabbar S5)
  POST /restart     -> supervisorctl restart google-chrome; returns result

Watchdog (same process, background thread): polls the local CDP HTTP port
every WATCHDOG_SECS; after WATCHDOG_FAILS consecutive failures it runs
`supervisorctl restart google-chrome` (Chrome crash -> self-heal < 1 min,
FR-16 soak acceptance) and logs the event. Counter resets on any success.

D5 tab persistence (2026-08-17) — Chrome-native session restore is broken
in CfT 128 kiosk (orphaned Session_/Tabs_ token pairs; startup URL and
kiosk both override --restore-last-session; no Last Session written on
stop). DoD chose the agent-managed snapshot as the mechanism:
  - every watchdog tick (30 s), while CDP is up, snapshot the open
    http(s) page URLs to $PROFILE/tab-snapshot.json (profile volume =
    persistent across container recreates; file is root-writable here).
  - on Chrome (re)start — watchdog recovery, watchdog-initiated restart,
    POST /restart, or process boot with the browser at an empty state —
    re-open the snapshot URLs via the plain-HTTP CDP endpoints
    (PUT /json/new?<url>), then close the leftover chrome://newtab.
  No websocket client needed (pure stdlib survives container recreates).

Session cookies already survive restarts (Chrome persists the cookie DB
periodically) — verified 2026-08-17: CRM SSO session intact after a
Chrome restart; only the TABS were lost. That is what this restores.

Env: LISTEN_PORT (default 9230), WATCHDOG_SECS (30), WATCHDOG_FAILS (3),
MAX_RUNNING_BROWSERS (2). PROFILE_DIR (default
/home/neko/.config/google-chrome-w1 — the viewer; fleet slots pass
/home/neko/.config/google-chrome) — restart-api is deployed per-container:
viewer on its profile, each fleet slot on its own profile, so the watchdog
and tab restore always act on the LOCAL chrome program.

D9 fleet gate (2026-08-17) — FR-16 MAX_RUNNING_BROWSERS:
  GET  /fleet          -> {running_browsers, cap, saturated, message}
  POST /fleet/request  -> 200 granted / 503 clear saturation message
  POST /fleet/test     -> dev/test hook: {cap: N} in-memory override,
                          {clear: true} resets (documented; the override
                          resets when this process restarts)
In dev01 the gate runs inside the single viewer container, so
running_browsers = 1 (this browser, CDP up) else 0. A multi-instance fleet
controller (W3) replaces that with a registry count; the message contract
stays.

Spec 29 idle suspend/resume (2026-08-21) — fleet slot reaper:
  Unified activity = human_active OR agent_active; a session is idle when
  NO enabled source reports activity for IDLE_TIMEOUT_MIN:
    xinput  -> X11 idle via XScreenSaverQueryInfo (ctypes+libXss; the neko
               image ships libXss.so.1; Xvfb implements MIT-SCREEN-SAVER).
               A human moving the mouse / typing resets X idle.
    media   -> ESTABLISHED sockets on the NEKO_EPR UDP range in
               /proc/net/udp = a WebRTC peer (the human viewer) is
               connected and watching.
    tabs    -> the open http(s) tab set / URLs changed (navigation).
    cdp     -> mtime of /tmp/cdp-activity, touched by cdp-relay v3 on
               every client->browser command — THE agent signal (CDP
               commands bypass X11 and the router, so relay-side
               timestamping is the only honest source).
  Idle >= IDLE_TIMEOUT_MIN  -> grace (GET /idle exposes status; the tabbar
  content script polls and shows a countdown toast).
  Idle >= TIMEOUT + GRACE   -> SUSPEND: stop chrome, snapshot, archive the
  profile (minus caches) + Downloads to /data/sessions/<user> (sessions
  volume), wipe the slot profile so the next human never inherits identity,
  then POST /fleet/release to the router (frees the sticky + records the
  archive). The reaper retries the router call until it lands.
  Resume: the router picks a free slot and POSTs /wake {user}; we restore
  the archive onto the profile, start chrome, restore tabs from the
  snapshot. Watchdog is suspended-aware (never restarts a suspended
  browser, or it would fight the suspend).
  The slot learns its user from the router's /identify push (router knows
  the sticky map); persisted to $DOWNLOADS/.slot-user.json (downloads
  volume is slot-bound and never wiped).
  Viewer: IDLE_ACTION=none keeps the reference viewer out of this loop.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "9230"))
WATCHDOG_SECS = int(os.environ.get("WATCHDOG_SECS", "30"))
WATCHDOG_FAILS = int(os.environ.get("WATCHDOG_FAILS", "3"))
CDP_HTTP = "http://127.0.0.1:9222"
PROFILE = os.environ.get(
    "PROFILE_DIR", "/home/neko/.config/google-chrome-w1")
SNAPSHOT_FILE = os.path.join(PROFILE, "tab-snapshot.json")
# W3-7: independent recovery copy. It is updated only after a complete
# validated live snapshot and is never used as a second restore writer.
LAST_GOOD_SNAPSHOT_FILE = os.path.join(PROFILE, "tab-snapshot.last-good.json")
SNAPSHOT_MAX = 10
# Spec 61b (2026-08-25): a snapshot is the source of truth for restore —
# it must NEVER shrink below a good state. A watchdog pass landing
# mid-restore (only 1 of 3 tabs loaded yet) or right after an eviction
# would otherwise overwrite a good 3-tab snapshot with a 1-tab one, and
# the next restore loses tabs (observed live: 3 tabs → 1 after a Chrome
# restart). Rules:
#   - if the existing snapshot has MORE urls than the live set, keep the
#     existing one unless it is older than SNAPSHOT_STALE_S (a genuinely
#     closed tab set eventually persists);
#   - if the live set is a SUPERSET (restore in progress), overwrite.
SNAPSHOT_STALE_S = int(os.environ.get("SNAPSHOT_STALE_S", "300"))
EMPTY_URLS = {"chrome://newtab/", "about:blank", "chrome://new-tab-page/"}
SUPERVISORCTL = "/usr/bin/supervisorctl"
CHROME_PROG = "google-chrome"
TITLE_PROXY_PROG = "title-proxy"
MAX_RUNNING_BROWSERS = int(os.environ.get("MAX_RUNNING_BROWSERS", "2"))

# --- Spec 29 idle suspend/resume (2026-08-21) ---------------------------
IDLE_TIMEOUT = int(os.environ.get("IDLE_TIMEOUT_MIN", "15")) * 60
IDLE_GRACE = int(os.environ.get("IDLE_GRACE_MIN", "5")) * 60
IDLE_CHECK = int(os.environ.get("IDLE_CHECK_INTERVAL", "60"))
IDLE_ACTION = os.environ.get("IDLE_ACTION", "suspend").lower()
IDLE_SOURCES = [s.strip() for s in os.environ.get(
    "IDLE_ACTIVITY_SOURCES", "xinput,media,tabs,cdp").split(",") if s.strip()]
SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "/data/sessions")
# Spec 55: archive is skipped when the on-disk profile is below this size
# (bytes) and an existing archive is present — an empty shell must never
# overwrite a real archive.
MIN_PROFILE_ARCHIVE_B = int(os.environ.get("MIN_PROFILE_ARCHIVE_B", "5242880"))
ROUTER_URL = os.environ.get("ROUTER_URL", "http://router:8081")
CDP_ACTIVITY_FILE = "/tmp/cdp-activity"
DOWNLOADS_DIR = os.environ.get("DOWNLOADS_DIR", "/home/neko/Downloads")
SLOT_USER_FILE = os.path.join(DOWNLOADS_DIR, ".slot-user.json")
# Cache/state dirs never archived (tens of MB of churn, fully regenerable).
ARCHIVE_EXCLUDE = {"Cache", "Code Cache", "GPUCache", "ShaderCache",
                   "DawnCache", "GrShaderCache", "DawnGraphiteCache"}
# Root-level entries inside PROFILE never archived and never wiped.
# CfT binaries live as siblings under /home/neko/.config/cft-chrome-* and are
# therefore outside the per-user profile lifecycle. The tab snapshot is NOT
# kept on wipe: the archive holds the old user's copy and a fresh slot must
# boot with zero tabs for the next user.
PROFILE_KEEP: set = set()
# EPR range for the media source (NEKO_EPR, e.g. "52101-52200").
_EPR = os.environ.get("NEKO_EPR", "")
try:
    _EPR_LO, _EPR_HI = (int(x) for x in _EPR.split("-"))
except ValueError:
    _EPR_LO = _EPR_HI = -1

_slot_user: str | None = None
_slot_index: int | None = None  # router /identify push (spec 29b); the
# hostname is an opaque container ID, so the router tells us our index
_suspended = False
_last_tab_set: frozenset | None = None
_last_tab_activity: float | None = None
_grace_until: float | None = None
# Spec 48 (capture-surface UX): a surface URL the ROUTER asked us to open
# (landing ?goto= or session-page /kiosk/open) that arrived while Chrome
# was down. Consumed by the next restore_tabs()/boot_restore() pass.
_pending_start_url: str | None = None
# Spec 77 (2026-08-28): owner-bound boot hint. Set on container boot
# when slot_user() is empty AND a real archive exists in SESSIONS_DIR.
# The /health payload exposes it so the router can dispatch /wake.
# None means "no hint" (already bound, no archive, or hint consumed).
_boot_archive_owner_value: str | None = None

# --- Spec 42 isolation (2026-08-22): chrome-ownership tracking ----------
# _started_for_user = user for whom the currently running chrome process
# was started (set in do_wake after a start). The disk profile may be
# swapped only while chrome is STOPPED; snapshotting a chrome that does
# not own the profile would archive another user's tabs (incident 41).
_started_for_user: str | None = None
_started_pid: int | None = None


def record_chrome_start(user: str) -> None:
    """Spec 42: remember which user the just-started chrome belongs to."""
    global _started_for_user, _started_pid, _restore_done
    _started_for_user = user
    _started_pid = _chrome_main_pid()
    # Spec 61: a fresh Chrome start gets a fresh restore opportunity.
    _restore_done = False


def clear_chrome_start() -> None:
    global _started_for_user, _started_pid, _restore_done
    _started_for_user = None
    _started_pid = None
    _restore_done = False


def chrome_owns_profile() -> bool:
    """Spec 42: True iff the running chrome was started for the current
    slot user (the disk profile's owner). When False, snapshotting the
    running chrome would capture another user's tabs."""
    return _started_for_user is not None and _started_for_user == slot_user()


def _chrome_running() -> bool:
    st = sup_status()
    return bool(st and st.get(CHROME_PROG) == "RUNNING")


# ---- spec 29: activity sources ----------------------------------------
_X_ERR_HANDLER = None  # keep the no-op X error handler referenced


def _x_idle_seconds() -> float | None:
    """X11 idle (s) via XScreenSaverQueryInfo. None = query failed (the
    source then contributes nothing — it can never force a suspend).
    A no-op X error handler is installed because Xlib's DEFAULT handler
    calls exit() on ANY protocol error (e.g. a bad drawable), which would
    kill the whole restart-api process."""
    global _X_ERR_HANDLER
    try:
        import ctypes
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        x11.XSetErrorHandler.restype = ctypes.c_void_p

        if _X_ERR_HANDLER is None:
            _ERRFN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                      ctypes.c_void_p)

            @_ERRFN
            def _noop(_dpy, _ev):
                return 0  # swallow the protocol error instead of exiting

            _X_ERR_HANDLER = _noop
            x11.XSetErrorHandler(_noop)

        xss = ctypes.CDLL("libXss.so.1")
        xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        xss.XScreenSaverQueryInfo.restype = ctypes.c_int

        class _Info(ctypes.Structure):
            _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int),
                        ("kind", ctypes.c_int), ("til_or_since", ctypes.c_ulong),
                        ("idle", ctypes.c_ulong), ("eventMask", ctypes.c_ulong)]

        dpy = x11.XOpenDisplay(os.environ.get("DISPLAY", ":99").encode())
        if not dpy:
            return None
        try:
            root = x11.XDefaultRootWindow(dpy)
            info = _Info()
            ok = xss.XScreenSaverQueryInfo(dpy, root, ctypes.byref(info))
            x11.XSync(dpy, 0)  # flush any async X error inside the try
            return info.idle / 1000.0 if ok else None
        finally:
            x11.XCloseDisplay(dpy)
    except Exception as e:
        print(f"idle: xinput probe failed: {e}", flush=True)
        return None


def _media_active() -> bool:
    """Human viewer attached? Two signals, either one counts:
      1. ESTABLISHED TCP to the slot's neko :8080 from a NON-loopback
         remote — the neko client page keeps its /ws session open while
         a human has the cloudbrowser window open (agents drive via CDP
         :9223 and never touch :8080).
      2. ESTABLISHED UDP on the NEKO_EPR range (WebRTC media flow)."""
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            for line in open(fn).read().splitlines()[1:]:
                f = line.split()
                if len(f) < 4:
                    continue
                lp, rp = f[1], f[2]
                lport = int(lp.split(":")[1], 16)
                if lport != 8080:
                    continue
                if int(f[3], 16) != 1:  # ESTABLISHED
                    continue
                remote_ip = rp.split(":")[0]
                # Loopback in all three spellings: IPv4 127.0.0.1, pure
                # IPv6 ::1, and IPv6-mapped ::ffff:127.0.0.1 (the title-proxy
                # WS relay shows up in /proc/net/tcp6 as the mapped form —
                # missing it made every open client session look like a
                # remote viewer, so the reaper never suspended).
                rip = remote_ip.lower()
                if rip in ("0100007f", "00000000000000000000000001000000") \
                        or rip.endswith("ffff00000100007f"):
                    continue
                return True  # non-loopback client session
        except Exception:
            continue
    if _EPR_LO < 0:
        return False
    for fn in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            for line in open(fn).read().splitlines()[1:]:
                f = line.split()
                if len(f) < 4:
                    continue
                lp = int(f[1].split(":")[1], 16)
                if int(f[3], 16) == 1 and _EPR_LO <= lp <= _EPR_HI:
                    return True
        except Exception:
            continue
    return False


def _tabs_activity_now() -> None:
    """Tabs source: record 'now' when the open tab set/URLs change."""
    global _last_tab_set, _last_tab_activity
    try:
        cur = frozenset(page_urls())
    except Exception:
        return
    if _last_tab_set is not None and cur != _last_tab_set:
        _last_tab_activity = time.time()
    _last_tab_set = cur


def _cdp_activity() -> float | None:
    try:
        return os.path.getmtime(CDP_ACTIVITY_FILE)
    except OSError:
        return None


def last_activity() -> float | None:
    """Latest activity across enabled sources, or None if NO source can
    measure (fail-safe: an unmeasurable session is treated as active —
    we never suspend something we cannot see)."""
    now = time.time()
    acts = []
    for s in IDLE_SOURCES:
        if s == "xinput":
            idle = _x_idle_seconds()
            if idle is not None:
                acts.append(now - idle)
        elif s == "media":
            if _media_active():
                acts.append(now)
        elif s == "tabs":
            _tabs_activity_now()
            if _last_tab_activity:
                acts.append(_last_tab_activity)
        elif s == "cdp":
            t = _cdp_activity()
            if t:
                acts.append(t)
    if not acts:
        print("idle: no activity source available — treating as active",
              flush=True)
        return now
    return max(acts)


# ---- spec 29: slot identity + archive ---------------------------------
def slot_user() -> str | None:
    """Current slot user (router /identify push); persisted so the reaper
    survives a restart-api restart mid-session."""
    global _slot_user, _slot_index
    if _slot_user is None:
        try:
            with open(SLOT_USER_FILE) as f:
                data = json.load(f)
                _slot_user = data.get("user")
                _slot_index = data.get("slot")
        except Exception:
            pass
    return _slot_user


# Spec 77 (2026-08-28): owner-bound boot hint. Computed on demand from
# the persistent sessions volume when the slot has no .slot-user.json.
# Used by `main()` to seed `_boot_archive_owner_value` and by the
# /health payload (so the router can dispatch a wake without
# re-implementing filesystem layout).
def _has_real_archive(user_dir: str) -> bool:
    """An archive counts as 'real' when it has a Chrome profile with at
    least a Preferences file. Empty directories (cleaned sessions, in-
    flight restores) are skipped — the router must not auto-wake an
    owner whose archive was wiped."""
    if not os.path.isdir(user_dir):
        return False
    prof = os.path.join(user_dir, "profile")
    if not os.path.isdir(os.path.join(prof, "Default")):
        return False
    if not os.path.isfile(os.path.join(prof, "Preferences")):
        return False
    return True


def _boot_archive_owner() -> str | None:
    """Spec 77: most-recent real archive owner (deterministic, by mtime).

    Called by `main()` on container boot when `slot_user()` is None. The
    router's /health poll then dispatches a `/wake <owner>` and the
    standard restore path runs. Returns None if the slot is already
    bound, the sessions volume is unreachable, or no real archive
    exists.
    """
    if slot_user():
        return None
    if not os.path.isdir(SESSIONS_DIR):
        return None
    candidates = []
    try:
        for name in os.listdir(SESSIONS_DIR):
            user_dir = os.path.join(SESSIONS_DIR, name)
            if _has_real_archive(user_dir):
                # mtime of the profile/Default directory (last touch).
                mtime = os.path.getmtime(
                    os.path.join(user_dir, "profile", "Default"))
                candidates.append((mtime, name))
    except Exception:
        return None
    if not candidates:
        return None
    candidates.sort(reverse=True)  # newest first
    return candidates[0][1]


def set_slot_user(user: str, slot: int | None = None) -> None:
    global _slot_user, _slot_index, _boot_archive_owner_value
    _slot_user = user
    if slot is not None:
        _slot_index = slot
    # Spec 77: binding an owner consumes the one-shot boot hint — the
    # archive recovery already happened (or a human took the slot). The
    # hint re-arms ONLY on a fresh container boot with the same
    # precondition; a released slot must never auto-re-wake from the
    # stale hint.
    _boot_archive_owner_value = None
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        # Spec 65 (2026-08-27, live): a re-assert of the SAME owner (the
        # router /identify sweep, every IDENTIFY_SWEEP_INTERVAL) must NOT
        # rewrite the marker. The broker's marker_snapshot() treats the ts
        # as the identity generation; a churning ts made it cancel every
        # fresh OTP challenge seconds after arming — the MFA load loop.
        # Only a real owner/slot change rotates the generation.
        try:
            with open(SLOT_USER_FILE) as f:
                cur = json.load(f)
        except Exception:
            cur = {}
        same = (str(cur.get("user") or "").strip().lower()
                == str(user).strip().lower()
                and cur.get("slot") == _slot_index)
        if same and float(cur.get("ts") or 0) > 0:
            return
        tmp = SLOT_USER_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"user": user, "slot": _slot_index,
                       "ts": int(time.time())}, f)
        os.replace(tmp, SLOT_USER_FILE)
    except Exception as e:
        print(f"idle: persist slot user failed: {e}", flush=True)


def clear_slot_user() -> None:
    """Spec 67/68 per-user Downloads: forget the slot's current user
    (in-memory + on-disk marker) on suspend/release. A released slot
    must not advertise any user, and the next owner must never inherit
    the previous owner's identity via the stale marker."""
    global _slot_user, _slot_index
    _slot_user = None
    _slot_index = None
    try:
        os.remove(SLOT_USER_FILE)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"idle: clear slot user failed: {e}", flush=True)


def _copytree_excl(src: str, dst: str) -> None:
    """Copy a profile tree, excluding cache dirs. Merges into an existing
    (pre-cleared) dst."""
    def _ignore(d, names):
        return {n for n in names if n in ARCHIVE_EXCLUDE}
    shutil.copytree(src, dst, ignore=_ignore, symlinks=True,
                    dirs_exist_ok=True)


def archive_user(user: str) -> bool:
    """Profile (minus caches) + Downloads -> /data/sessions/<user>/.

    Spec 52 guard: NEVER overwrite a user's archive with an empty or
    half-restored profile. A profile with no `Default` dir or no
    `Preferences` is not a real session (it means a concurrent wake was
    mid-restore when the suspend ran, or the profile was already wiped) —
    archiving it would destroy the user's actual profile (seen live:
    montigaud's full archive was replaced by a 4 KiB empty one, and the
    slot came back up as the previous user)."""
    try:
        if not (os.path.isdir(os.path.join(PROFILE, "Default"))
                and os.path.isfile(os.path.join(PROFILE, "Preferences"))):
            print(f"idle: archive SKIPPED for {user} — profile on disk is "
                  f"empty/incomplete (no Default/Preferences); keeping the "
                  f"existing archive", flush=True)
            return False
        dest = os.path.join(SESSIONS_DIR, user)
        # Spec 55 (hardening): a profile can pass the Default/Preferences
        # check and still be an empty shell (a 4 KiB archive overwrote
        # spike-user's data live). If an existing archive is present and the
        # on-disk profile is suspiciously small (< MIN_PROFILE_ARCHIVE_B),
        # keep the existing archive — an empty shell must never replace a
        # real one.
        if os.path.isdir(dest):
            try:
                prof_bytes = sum(
                    os.path.getsize(os.path.join(r, f))
                    for r, _d, fs in os.walk(PROFILE) for f in fs)
            except OSError:
                prof_bytes = 0
            if prof_bytes < MIN_PROFILE_ARCHIVE_B:
                print(f"idle: archive SKIPPED for {user} — on-disk profile "
                      f"is only {prof_bytes} B (suspected empty shell); "
                      f"keeping the existing archive", flush=True)
                return False
        tmp = dest + ".tmp"
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        if os.path.isdir(PROFILE):
            _copytree_excl(PROFILE, os.path.join(tmp, "profile"))
        # Spec 68: never lose the user's tab snapshot across an archive
        # replacement. A destructive suspend (chrome_owns_profile False →
        # the stale live snapshot is deleted) must not erase the archive's
        # last-known tabs: if the new archive has no snapshot but the
        # previous archive did, carry the previous one over. (Live-verified
        # cause: montigaud's 3-tab snapshot vanished from the archive after
        # a guard-path suspend replaced the archive wholesale.)
        new_snap = os.path.join(tmp, "profile", "tab-snapshot.json")
        old_snap = os.path.join(dest, "profile", "tab-snapshot.json")
        if (not os.path.exists(new_snap) and os.path.exists(old_snap)):
            try:
                shutil.copy2(old_snap, new_snap)
                print(f"idle: preserved archive tab-snapshot for {user}",
                      flush=True)
            except Exception as e:
                print(f"idle: snapshot preserve failed: {e}", flush=True)
        # Spec 56: archives never carry SSO identity cookies.
        _strip_identity_cookies(os.path.join(tmp, "profile"))
        if os.path.isdir(DOWNLOADS_DIR):
            dl = os.path.join(tmp, "Downloads")
            os.makedirs(dl, exist_ok=True)
            for n in os.listdir(DOWNLOADS_DIR):
                if n.startswith(".slot-user"):
                    continue
                s = os.path.join(DOWNLOADS_DIR, n)
                if os.path.isdir(s):
                    shutil.copytree(s, os.path.join(dl, n), symlinks=True)
                else:
                    shutil.copy2(s, os.path.join(dl, n))
        # Spec 55: preserve the GrantHub grant store across archive.
        # /data/sessions/<user>/grant/ (GRANT_ROOT, router-written) must
        # survive session end or the user re-grants after every slot — the
        # old rmtree(dest) below destroyed it (observed live 2026-08-24:
        # grant wiped at archive → pill red despite the earlier grant).
        grant_src = os.path.join(dest, "grant")
        if os.path.isdir(grant_src):
            shutil.copytree(grant_src, os.path.join(tmp, "grant"),
                            symlinks=True)
            print(f"idle: preserved grant/ for {user}", flush=True)
        if os.path.isdir(dest):
            shutil.rmtree(dest, ignore_errors=True)
        # Spec 42 (D): owner marker — restore_user refuses a mismatch,
        # and the test suite verifies archive integrity with it.
        try:
            with open(os.path.join(tmp, ".archive-user.json"), "w") as f:
                json.dump({"user": user, "slot": _slot_index,
                           "ts": int(time.time())}, f)
        except Exception as e:
            print(f"idle: archive marker write failed: {e}", flush=True)
        os.replace(tmp, dest)
        print(f"idle: archived {user} ({os.path.getsize(dest) // 1024} KiB)",
              flush=True)
        return True
    except Exception as e:
        print(f"idle: archive FAILED for {user}: {e}", flush=True)
        return False


def _strip_identity_cookies(profile_dir: str) -> None:
    """Spec 56: never carry SSO identity cookies into an archive or a
    restored profile. A tinyauth session cookie (tinyauth-session-*, on
    .pmo.city) or an Authentik cookie (auth.aikumi.app) restored from
    another user's profile resurrects the PREVIOUS user's identity in the
    kiosk (seen live: montigaud's slot kept rendering GrantHub for
    spike-user because the archive held spike-user's tinyauth cookie).
    The session must SSO fresh as the slot owner on every wake. Chrome is
    stopped when this runs (archive / restore), so the Cookies DB is
    safe to edit."""
    db = os.path.join(profile_dir, "Default", "Cookies")
    if not os.path.isfile(db):
        return
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        cur.execute(
            "DELETE FROM cookies WHERE host_key LIKE '%.pmo.city%' "
            "OR host_key LIKE '%aikumi%' OR name LIKE 'tinyauth%'")
        n = cur.rowcount
        con.commit()
        con.close()
        if n:
            print(f"idle: stripped {n} identity cookie(s) from {db}",
                  flush=True)
    except Exception as e:
        print(f"idle: identity cookie strip failed for {db}: {e}", flush=True)


def wipe_slot_dirs() -> None:
    """Empty the per-user PROFILE + DOWNLOADS_DIR.

    CfT binaries live as siblings under /home/neko/.config/cft-chrome-* and are
    not inside PROFILE; no browser-version directory is special-cased here.
    Used by restore_user and by a fresh wake so the next owner inherits no
    prior-user browser state.
    """
    for d in (PROFILE, DOWNLOADS_DIR):
        os.makedirs(d, exist_ok=True)
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def restore_user(user: str) -> bool:
    """Archive -> slot profile + Downloads. Dest dirs are emptied first.
    Spec 42 (D): refuse to restore an archive whose owner marker names a
    DIFFERENT user (contamination detection, incident 41)."""
    try:
        src = os.path.join(SESSIONS_DIR, user)
        if not os.path.isdir(os.path.join(src, "profile")):
            print(f"idle: restore FAILED — no archive for {user}", flush=True)
            return False
        marker = os.path.join(src, ".archive-user.json")
        if os.path.isfile(marker):
            try:
                with open(marker) as f:
                    owner = json.load(f).get("user")
                if owner != user:
                    print(f"idle: restore REFUSED — archive {user} is "
                          f"owned by {owner} (contamination); fresh wake",
                          flush=True)
                    return False
            except Exception as e:
                print(f"idle: restore marker read failed: {e}", flush=True)
        else:
            # Pre-spec-42 archive (no marker): backward-compatible WARN.
            print(f"idle: restore {user} — archive has NO owner marker "
                  f"(pre-42), proceeding", flush=True)
        # Spec 52: never restore an empty/incomplete archive — an archive
        # whose profile lacks Default/Preferences is a broken shell (e.g. a
        # pre-spec-52 4 KiB overwrite). Treat as a fresh wake instead of
        # copying the empty shell onto the slot.
        if not (os.path.isdir(os.path.join(src, "profile", "Default"))
                and os.path.isfile(os.path.join(src, "profile", "Preferences"))):
            print(f"idle: restore {user} — archive profile is "
                  f"empty/incomplete (no Default/Preferences); fresh wake",
                  flush=True)
            return False
        wipe_slot_dirs()
        _copytree_excl(os.path.join(src, "profile"), PROFILE)
        # Spec 56: a restored profile never resurrects a stale SSO identity
        # (belt-and-suspenders for archives that predate the strip).
        _strip_identity_cookies(PROFILE)
        dl = os.path.join(src, "Downloads")
        if os.path.isdir(dl):
            for n in os.listdir(dl):
                s = os.path.join(dl, n)
                if os.path.isdir(s):
                    shutil.copytree(s, os.path.join(DOWNLOADS_DIR, n),
                                    symlinks=True)
                else:
                    shutil.copy2(s, os.path.join(DOWNLOADS_DIR, n))
        # 2026-08-21 (tabbar invisible bug): archives may hold root-owned
        # files (profile created while Chrome ran as root on an early fleet
        # image). Chrome now runs as neko (uid 1000); a root-owned extension
        # storage LevelDB rejects LOCK creation -> chrome.storage rejects ->
        # the tabbar content script never positions itself (invisible bar).
        # restart-api runs as root, so repair ownership here on every wake.
        try:
            subprocess.run(["chown", "-R", "neko:neko", PROFILE, DOWNLOADS_DIR],
                           check=False, capture_output=True)
        except Exception:
            pass
        print(f"idle: restored {user}", flush=True)
        return True
    except Exception as e:
        print(f"idle: restore FAILED for {user}: {e}", flush=True)
        return False


def wipe_profile() -> None:
    """Wipe the slot profile so the next human never inherits identity.
    cft-chrome-128 (the CfT binary) and the tab snapshot live outside/are
    regenerated — everything else goes."""
    try:
        if os.path.isdir(PROFILE):
            for n in os.listdir(PROFILE):
                if n in PROFILE_KEEP:
                    continue
                p = os.path.join(PROFILE, n)
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
        print("idle: slot profile wiped", flush=True)
    except Exception as e:
        print(f"idle: wipe FAILED: {e}", flush=True)


# ---- spec 29: suspend / wake ------------------------------------------
def notify_router_release(user: str, reason: str | None = None) -> bool:
    payload = {"user": user}
    if reason:
        payload["reason"] = reason
    try:
        req = urllib.request.Request(
            ROUTER_URL + "/fleet/release", method="POST",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            ok = r.status == 200
        print(f"idle: router release {'ok' if ok else r.status}"
              f" (reason={reason})", flush=True)
        return ok
    except Exception as e:
        print(f"idle: router release failed: {e}", flush=True)
        return False


def _do_suspend_impl(reason: str | None = None) -> None:
    """Stop chrome -> fresh snapshot -> archive -> wipe -> router release.
    Idempotent: safe to re-run (e.g. router release retried).
    Spec 32: reason='released' (tab bar Exit) — same teardown as the
    reaper/idle paths, but the archive is labelled user-initiated."""
    global _suspended
    user = slot_user()
    if not user:
        # A slot may reboot/redeploy with supervisor autostarting Chrome but
        # without an owner marker. The router then sees users={}, yet its
        # isolation gate refuses the slot forever because suspended=false.
        # This is not a user session: fail closed by stopping browser-facing
        # processes, wiping owner-scoped state, and marking the slot clean.
        if not _chrome_running():
            _suspended = True
            print("idle: ownerless slot already stopped — marked suspended",
                  flush=True)
            return
        print("idle: SANITIZE ownerless running slot", flush=True)
        try:
            r = subprocess.run([SUPERVISORCTL, "stop", CHROME_PROG],
                               capture_output=True, text=True, timeout=60)
            print("idle: ownerless chrome stopped:",
                  (r.stdout + r.stderr).strip()[-200:], flush=True)
        except Exception as e:
            print(f"idle: ownerless chrome stop failed: {e}", flush=True)
        clear_chrome_start()
        try:
            r = subprocess.run([SUPERVISORCTL, "stop", TITLE_PROXY_PROG],
                               capture_output=True, text=True, timeout=60)
            print("idle: ownerless title-proxy stopped:",
                  (r.stdout + r.stderr).strip()[-120:], flush=True)
        except Exception as e:
            print(f"idle: ownerless title-proxy stop failed: {e}", flush=True)
        wipe_slot_dirs()
        clear_slot_user()
        _suspended = True
        return
    if _suspended:
        # Spec 45: a stale _suspended flag must not silently swallow a real
        # suspend. If Chrome is ACTUALLY running, we must still tear down
        # (the flag was left stale by a Chrome start that bypassed /wake —
        # e.g. supervisorctl start or the spec-40 rescue). Only skip when
        # Chrome is genuinely stopped.
        if not _chrome_running():
            print("idle: suspend skipped — already suspended (chrome not "
                  "running)", flush=True)
            return
        print("idle: suspend STALE flag — chrome running, forcing teardown",
              flush=True)
    print(f"idle: SUSPEND user={user}", flush=True)
    if not chrome_owns_profile():
        # Spec 42 isolation guard: the running chrome is not the one we
        # started for this user (stale/foreign process). Snapshotting it
        # would archive another user's tabs into this user's archive
        # (incident 41). Fail-safe: skip snapshot + clear any stale one.
        print("idle: SUSPEND isolation guard — chrome does not own the "
              "profile; snapshot skipped, stale snapshot cleared", flush=True)
        for snapshot_path in (SNAPSHOT_FILE, LAST_GOOD_SNAPSHOT_FILE):
            try:
                os.remove(snapshot_path)
            except FileNotFoundError:
                pass
    else:
        try:
            snapshot_tabs()  # freshest tabs while CDP is still up
        except Exception as e:
            print(f"idle: pre-suspend snapshot failed: {e}", flush=True)
    try:
        r = subprocess.run([SUPERVISORCTL, "stop", CHROME_PROG],
                           capture_output=True, text=True, timeout=60)
        print("idle: chrome stopped:",
              (r.stdout + r.stderr).strip()[-200:], flush=True)
    except Exception as e:
        print(f"idle: chrome stop failed: {e}", flush=True)
    clear_chrome_start()
    # Drop the member session so neko's encode pipeline actually pauses:
    # the client's WS reaches neko through title-proxy, so stopping it
    # disconnects the session (chrome being stopped alone leaves neko
    # encoding a static screen at ~1 core forever while the tab is open).
    try:
        r = subprocess.run([SUPERVISORCTL, "stop", TITLE_PROXY_PROG],
                           capture_output=True, text=True, timeout=60)
        print("idle: title-proxy stopped (session dropped):",
              (r.stdout + r.stderr).strip()[-120:], flush=True)
    except Exception as e:
        print(f"idle: title-proxy stop failed: {e}", flush=True)
    if archive_user(user):
        # Spec 67/68 per-user Downloads: wipe the SLOT dirs (profile AND
        # the slot's Downloads volume) after archiving, and clear the
        # slot-user marker. The slot must never physically retain one
        # user's files for the next user — Downloads is per-user (the
        # archive under /data/sessions/<user>/Downloads is the durable
        # per-user store), exactly like the profile. Previously only the
        # profile was wiped, so the slot Downloads volume accumulated
        # user files across owners (Tigo: "slots are shared, users don't
        # share anything").
        wipe_slot_dirs()
        clear_slot_user()
    _suspended = True
    if not notify_router_release(user, reason):
        # Router unreachable — retry every reaper tick (do_suspend returns
        # early on _suspended, so re-run the notify in the reaper instead).
        threading.Thread(target=_retry_release, args=(user, reason),
                         daemon=True).start()


def do_suspend(reason: str | None = None) -> None:
    """Public entry (spec 52): serialise against do_wake / release."""
    with _lifecycle_lock:
        _do_suspend_impl(reason)


def _retry_release(user: str, reason: str | None = None) -> None:
    for _ in range(30):  # ~30 min of retries
        time.sleep(60)
        if notify_router_release(user, reason):
            return


def do_wake(user: str) -> dict:
    """Public entry (spec 52): serialise against do_suspend / release."""
    with _lifecycle_lock:
        return _do_wake_impl(user)


def _do_wake_impl(user: str) -> dict:
    """Restore an archive onto this slot and start chrome. Called by the
    router when a returning user's request lands on this slot. Spec 31:
    a user with NO archive (fresh user) still gets a plain wake on an
    empty profile — previously this 500'd and the router could never
    grant a suspended slot to a new user.
    Spec 42 (isolation, incident 41): a slot's chrome and its on-disk
    profile must ALWAYS belong to the same user. A user switch therefore
    STOPS chrome + title-proxy before touching the profile; a same-user
    re-offer is a no-op while chrome is already up. Spec 72 additionally
    re-runs the restore consumer when that browser has no real tabs."""
    global _suspended, _grace_until, _need_restore, _restore_done
    cur = slot_user()
    if cur == user and _chrome_running() and not _need_restore:
        # Same user, chrome already up: do not touch the profile.  Still run
        # the single restore consumer when Chrome has no real tabs: a prior
        # crash/manual start can leave only chrome://newtab, and returning
        # "already up" would strand the user on a blank kiosk.  restore_tabs()
        # is serialized and guarded by _restore_done, so this is harmless when
        # a valid tab workspace is already present.
        _suspended = False
        _grace_until = None
        if not page_urls():
            print(f"idle: wake same-user {user} — zero tabs, restoring",
                  flush=True)
            _need_restore = False
            _restore_done = False
            threading.Thread(target=restore_tabs, daemon=True).start()
            return {"ok": True, "user": user, "note": "restore requested"}
        print(f"idle: wake same-user {user} — already up (no-op)", flush=True)
        return {"ok": True, "user": user, "note": "already up"}
    if _chrome_running():
        # User switch (or stale chrome from a previous user): stop chrome +
        # title-proxy BEFORE touching the profile. Isolation invariant.
        print(f"idle: wake user-switch {cur or '?'} -> {user} — stopping chrome",
              flush=True)
        try:
            subprocess.run([SUPERVISORCTL, "stop", CHROME_PROG],
                           capture_output=True, text=True, timeout=60)
            subprocess.run([SUPERVISORCTL, "stop", TITLE_PROXY_PROG],
                           capture_output=True, text=True, timeout=60)
            clear_chrome_start()
        except Exception as e:
            print(f"idle: wake stop-chrome failed: {e}", flush=True)
    if not restore_user(user):
        print(f"idle: no archive for {user} — fresh wake (empty profile)",
              flush=True)
        wipe_slot_dirs()
    set_slot_user(user)
    _suspended = False
    _grace_until = None
    try:
        r = subprocess.run([SUPERVISORCTL, "start", CHROME_PROG],
                           capture_output=True, text=True, timeout=60)
        print("idle: chrome started:",
              (r.stdout + r.stderr).strip()[-200:], flush=True)
    except Exception as e:
        print(f"idle: chrome start failed: {e}", flush=True)
    # The suspend path stops title-proxy (drops the neko member session so
    # the encode pipeline pauses). Bring the UI front back on wake.
    try:
        r = subprocess.run([SUPERVISORCTL, "start", TITLE_PROXY_PROG],
                           capture_output=True, text=True, timeout=60)
        print("idle: title-proxy started:",
              (r.stdout + r.stderr).strip()[-120:], flush=True)
    except Exception as e:
        print(f"idle: title-proxy start failed: {e}", flush=True)
    # Spec 42: record which user this chrome now serves.
    record_chrome_start(user)
    # Spec 63 (2026-08-25): reset the idle baseline on wake. The X idle
    # clock does NOT reset when Chrome starts — after an idle/session-end
    # the freshly-woken slot still reports the pre-wake idle time, so the
    # reaper suspended it ~34 s after wake (observed live: wake 10:55:52
    # → SUSPEND 10:56:26) → the neko client lost its WS → "PLEASE LOG
    # IN"/black stream on every reload (Tigo's recurring hang). Touching
    # the cdp-activity marker + the tab-activity clock gives the idle
    # monitor a fresh baseline: the slot now has the full IDLE_TIMEOUT
    # budget after every wake.
    try:
        open(CDP_ACTIVITY_FILE, "a").close()  # cdp source (mtime = now)
    except Exception:
        pass
    global _last_tab_activity, _wake_at
    _last_tab_activity = time.time()  # tabs source
    _wake_at = time.time()  # spec 63: idle baseline floor for the reaper
    # Tab restore: an explicit wake owns ONE immediate consumer. Waiting for
    # the watchdog's next PID poll added up to WATCHDOG_SECS before restore
    # even began (live 2026-08-26: MontyGo take 12:14:52, tabs 12:15:20).
    # restore_tabs() is serialized by _restore_lock and guarded by
    # _restore_done, so a later watchdog PID observation is a harmless no-op.
    # Do not leave _need_restore set here: this thread is the consumer.
    _need_restore = False
    threading.Thread(target=restore_tabs, daemon=True).start()
    return {"ok": True, "user": user}


def idle_status() -> dict:
    now = time.time()
    last = last_activity()
    if _suspended:
        status = "suspended"
    elif last is not None and now - last < IDLE_TIMEOUT:
        status = "active"
    elif _grace_until is not None and now < _grace_until:
        status = "grace"
    else:
        status = "idle"
    return {"ok": True, "status": status, "user": slot_user(),
            "timeoutMin": IDLE_TIMEOUT // 60, "graceMin": IDLE_GRACE // 60,
            "sources": IDLE_SOURCES, "lastActivity": last,
            "idleFor": (now - last) if last is not None else None,
            "graceUntil": _grace_until,
            "secondsLeft": max(0, int(_grace_until - now)) if _grace_until else None}


def reaper_loop() -> None:
    """Check cadence IDLE_CHECK_INTERVAL; grace -> suspend at timeout."""
    global _grace_until, _wake_at
    if IDLE_ACTION != "suspend":
        print(f"idle: reaper disabled (IDLE_ACTION={IDLE_ACTION})",
              flush=True)
        return
    print(f"idle: reaper start timeout={IDLE_TIMEOUT // 60}min "
          f"grace={IDLE_GRACE // 60}min sources={','.join(IDLE_SOURCES)}",
          flush=True)
    while True:
        time.sleep(IDLE_CHECK)
        if _suspended:
            continue
        last = last_activity()
        # Spec 63: a freshly woken slot must NEVER be suspended from a
        # stale idle clock. The X idle counter does not reset when Chrome
        # starts, so right after a wake the X source still reports the
        # pre-wake idle (observed live: wake → SUSPEND 2 s later → the
        # neko client lost its WS → "PLEASE LOG IN" on every reload).
        # The wake moment is activity: use it as the floor of the idle
        # baseline until real input takes over.
        if _wake_at and _wake_at > last:
            last = _wake_at
        now = time.time()
        idle_for = now - last if last is not None else 0.0
        if idle_for < IDLE_TIMEOUT:
            if _grace_until is not None:
                print(f"idle: activity resumed (idle {idle_for:.0f}s) — "
                      "grace cancelled", flush=True)
            _grace_until = None
            continue
        if _grace_until is None:
            _grace_until = last + IDLE_TIMEOUT + IDLE_GRACE
            print(f"idle: GRACE — idle {idle_for:.0f}s, suspend at "
                  f"{time.strftime('%H:%M:%S', time.localtime(_grace_until))}",
                  flush=True)
        elif now >= _grace_until:
            _grace_until = None
            do_suspend()

# Tabbar S1/S4/S5 (2026-08-21): homepage-if-zero-tabs + tab limit, driven
# from the compose env (Coolify env table overrides). Exposed to the
# extension via GET /config (MV3 cannot read env vars).
HOME_URL = os.environ.get("HOME_URL", "https://pmo.city")
try:
    TAB_LIMIT = max(1, int(os.environ.get("TAB_LIMIT", "3")))
except ValueError:
    TAB_LIMIT = 3

# D9 fleet gate state (dev test hook — in-memory only, resets on restart)
_fleet_cap_override: int | None = None

SATURATION_MSG = ("All browser slots are busy (cap reached: {cap}). "
                  "Please retry later, or ask an administrator to raise "
                  "MAX_RUNNING_BROWSERS.")

_restore_lock = threading.Lock()
_need_restore = False  # set by watchdog/restart, consumed by the restorer
_restore_done = False  # spec 61: restore ran for the CURRENT chrome start
_wake_at: float = 0.0  # spec 63: last do_wake moment (idle baseline floor)
_chrome_pid_baseline: int | None = None  # W3: watchdog's Chrome PID baseline

# Spec 52 (2026-08-24, Tigo): serialise the slot lifecycle. do_wake /
# do_suspend / release are invoked from threaded HTTP handlers and from
# the idle/reaper loops; without a lock, a /wake (restore -> start) can
# interleave with a /suspend (stop -> archive -> wipe), producing a
# half-restored profile that gets archived as a 4 KiB EMPTY archive and
# overwrites the user's real archive — the incident where montigaud's
# slot came up as the PREVIOUS user (spike-user) because the running
# Chrome kept the old in-memory session across the broken swap.
_lifecycle_lock = threading.Lock()

# Spec 39: wedged-neko rescue rate limit (min seconds between restarts).
CB_RESET_COOLDOWN_S = float(os.environ.get("CB_RESET_COOLDOWN_S", "60"))
_rescue_last: float = 0.0

# Spec 40: blank-page wedge backstop. If the slot is occupied and neko's
# log ends on a session-teardown line (last listener leaving / session
# destroyed) with nothing written since for > CB_STREAM_GUARD_S, neko
# accepted connections but never restarted its pipeline — restart it.
NEKO_LOG = os.environ.get("NEKO_LOG", "/var/log/neko/neko.log")
CB_STREAM_GUARD_S = float(os.environ.get("CB_STREAM_GUARD_S", "90"))
_heals: int = 0  # spec 40 stream-guard auto-restarts (surfaced in /health)


def neko_wedged(log_path: str = NEKO_LOG, guard_s: float = CB_STREAM_GUARD_S) -> bool:
    """True when neko's log ends on a teardown line and nothing has been
    written since for > guard_s — the 'destroyed session, never restarted'
    wedge signature (spec 40). A healthy active session ends on
    session-start/ICE lines; a healthy closed-tab slot goes idle (reaper
    owns it) or is free (slot_user() None — caller checks)."""
    try:
        if not os.path.exists(log_path):
            return False
        age = time.time() - os.path.getmtime(log_path)
        if age < guard_s:
            return False
        with open(log_path, "r", errors="replace") as f:
            lines = f.read().strip().splitlines()
        if not lines:
            return False
        last = lines[-1].lower()
        return ("destroying session" in last or "last listener, stopping" in last)
    except Exception:
        return False


def stream_guard_loop() -> None:
    global _rescue_last
    """Spec 40: periodic check — occupied slot + wedged neko → restart the
    neko app (same cooldown as /restart-neko). Heals the slot before the
    next login even when no viewer is open.

    Fires only when the CURRENT assignment has lasted > CB_STREAM_GUARD_S:
    a healthy login creates a new session (log lines) within seconds, so a
    slot whose log still ends on an old teardown line after a full guard
    window is genuinely wedged — and we never restart during the normal
    assignment→viewer-connect gap."""
    global _heals
    print(f"spec40: stream guard start guard_s={CB_STREAM_GUARD_S:.0f} "
          f"log={NEKO_LOG}", flush=True)
    seen: dict[str, float] = {}  # user → first-seen ts (assignment start)
    while True:
        time.sleep(10)
        try:
            if _suspended:
                continue
            user = slot_user()
            if user is None:
                seen.clear()
                continue
            now = time.time()
            first = seen.get(user)
            if first is None:
                seen[user] = now
                continue
            if now - first < CB_STREAM_GUARD_S:
                continue
            if not neko_wedged():
                continue
            if now - _rescue_last < CB_RESET_COOLDOWN_S:
                continue
            _rescue_last = now
            out = restart_neko()
            if out.get("ok"):
                _heals += 1
                print(f"spec40: stream-guard restarted neko "
                      f"(user={user}) heals={_heals}", flush=True)
            else:
                print(f"spec40: stream-guard restart failed: {out}", flush=True)
        except Exception as e:
            print(f"spec40: stream-guard error: {e}", flush=True)


def restart_neko() -> dict:
    """Spec 39: `supervisorctl restart neko` — the neko app process ONLY
    (never the container, never Chrome). Profile + open tabs survive; only
    the wedged WebRTC/auth server is recycled (~seconds)."""
    try:
        out = subprocess.run([SUPERVISORCTL, "restart", "neko"],
                             capture_output=True, text=True, timeout=30)
        return {"ok": out.returncode == 0,
                "detail": (out.stdout or out.stderr).strip()[:160]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def sup_status() -> dict:
    try:
        out = subprocess.run([SUPERVISORCTL, "status"], capture_output=True,
                             text=True, timeout=20).stdout
        progs = {}
        for line in out.strip().splitlines():
            parts = line.split(None, 2)
            if len(parts) >= 2:
                progs[parts[0]] = parts[1]
        return progs
    except Exception as e:
        return {"ok": False, "error": str(e)}


def restart_chrome() -> dict:
    try:
        r = subprocess.run([SUPERVISORCTL, "restart", CHROME_PROG],
                           capture_output=True, text=True, timeout=60)
        return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def cdp_ok() -> bool:
    try:
        with urllib.request.urlopen(CDP_HTTP + "/json/version", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def _http_json(path: str, method: str = "GET", timeout: int = 5):
    req = urllib.request.Request(CDP_HTTP + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _http_text(path: str, method: str = "GET", timeout: int = 5):
    """Chrome's /json/close returns non-JSON text — read raw."""
    req = urllib.request.Request(CDP_HTTP + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def page_urls() -> list:
    """Live http(s) page URLs (excludes chrome:// and extension pages)."""
    try:
        targets = _http_json("/json/list")
    except Exception:
        return []
    urls = []
    for t in targets:
        if t.get("type") != "page":
            continue
        u = t.get("url", "")
        if u.startswith("http") and "chrome-extension://" not in u:
            urls.append(u)
    return urls


def _write_snapshot_file(path: str, payload: dict,
                         optional: bool = False) -> bool:
    """Atomically write one snapshot file; optional copies fail closed."""
    parent = os.path.dirname(path)
    tmp = path + ".tmp"
    try:
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
        return True
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        if optional:
            print(f"tab-snapshot: optional copy unavailable: {e}", flush=True)
            return False
        raise


def snapshot_tabs() -> None:
    """D5: persist the current tab workspace to the profile volume.

    The homepage is omitted only when it is the sole real tab (the automatic
    zero-tabs fallback). When it coexists with another restorable tab it is
    user workspace state and must survive suspend/restore (spec 70). Spec 61
    still deduplicates URLs so an external open cannot multiply tabs.
    """
    candidates = []
    seen = set()
    for u in page_urls():
        if _is_sso_error(u):
            continue
        if not (u.startswith("http://") or u.startswith("https://")):
            continue
        if u in seen:
            continue
        seen.add(u)
        candidates.append(u)
    non_home = [u for u in candidates if not _is_home(u)]
    urls = candidates if non_home else []
    if not urls:
        return
    try:
        # Spec 61b: never shrink a good snapshot. Read the existing one
        # and keep it when it is richer and still fresh.
        try:
            with open(SNAPSHOT_FILE) as f:
                old = json.load(f)
            old_urls = [u for u in old.get("urls", [])
                        if isinstance(u, str) and u.startswith("http")
                        and not _is_sso_error(u)]
            old_ts = float(old.get("ts", 0))
        except Exception:
            old_urls, old_ts = [], 0
        if len(old_urls) > len(urls) and time.time() - old_ts < SNAPSHOT_STALE_S:
            print(f"tab-snapshot: KEPT richer snapshot "
                  f"({len(old_urls)} urls > live {len(urls)}, "
                  f"age {int(time.time() - old_ts)}s < {SNAPSHOT_STALE_S}s)",
                  flush=True)
            # W3-7: if the independent copy is missing or invalid, rebuild it
            # from the richer live state rather than losing the recovery copy.
            if old_urls and not _snapshot_file_is_valid(LAST_GOOD_SNAPSHOT_FILE):
                _write_snapshot_file(LAST_GOOD_SNAPSHOT_FILE, {
                    "ts": int(old_ts), "urls": old_urls[:SNAPSHOT_MAX]
                }, optional=True)
            return
        payload = {"ts": int(time.time()), "urls": urls[:SNAPSHOT_MAX]}
        # Write the live snapshot first, then commit the independent
        # last-good copy. Each replace keeps readers from seeing a partial
        # JSON document; a failure of the second write cannot damage the live
        # snapshot (and vice versa).
        _write_snapshot_file(SNAPSHOT_FILE, payload)
        _write_snapshot_file(LAST_GOOD_SNAPSHOT_FILE, payload, optional=True)
        print(f"tab-snapshot: saved last-good copy ({len(payload['urls'])} urls)",
              flush=True)
    except Exception as e:
        print(f"tab-snapshot: write failed: {e}", flush=True)


def _is_home(u: str) -> bool:
    """HOME_URL match (trailing-slash tolerant).

    The homepage is an automatic zero-tabs fallback only when it is alone.
    In a multi-tab workspace it is ordinary user state and is persisted and
    restored (spec 70)."""
    try:
        return u.rstrip("/") == HOME_URL.rstrip("/")
    except Exception:
        return False


# Spec 72 (2026-08-27): all Authentik login/authorization flow pages are
# transient authentication state, not user workspace. They must never be
# persisted or restored: replaying an old /if/flow URL strands the kiosk on a
# stale MFA challenge instead of allowing a fresh SSO flow.
SSO_ERROR_HOSTS = ("auth.pmo.city", "auth.aikumi.app")
SSO_ERROR_PATHS = ("/error",)
SSO_AUTH_FLOW_PREFIXES = ("/if/flow/", "/application/o/authorize")


def _is_sso_error(u: str) -> bool:
    try:
        p = urllib.parse.urlparse(u)
        if p.hostname not in SSO_ERROR_HOSTS:
            return False
        path = p.path.rstrip("/")
        return (path in SSO_ERROR_PATHS
                or any(path.startswith(prefix.rstrip("/"))
                       for prefix in SSO_AUTH_FLOW_PREFIXES))
    except Exception:
        return False


def _read_snapshot(path: str) -> tuple[bool, list]:
    """Return (valid, urls); valid distinguishes an intentional empty set."""
    try:
        with open(path) as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("urls"), list):
            return False, []
        urls = [u for u in d["urls"]
                if isinstance(u, str) and u.startswith("http")
                and not _is_sso_error(u)]
        # A homepage-only list is a valid intentional zero-workspace state.
        return True, (urls if any(not _is_home(u) for u in urls) else [])
    except Exception:
        return False, []


def _snapshot_urls(path: str) -> list:
    return _read_snapshot(path)[1]


def _snapshot_file_is_valid(path: str) -> bool:
    return _read_snapshot(path)[0]


def load_snapshot() -> list:
    # W3-7: the live file is authoritative when valid, including a valid
    # empty workspace. Only an unreadable/malformed live file falls back to
    # the independent last-good copy.
    valid, urls = _read_snapshot(SNAPSHOT_FILE)
    if valid:
        return urls
    return _snapshot_urls(LAST_GOOD_SNAPSHOT_FILE)


def all_empty(urls: list) -> bool:
    return all(u in EMPTY_URLS for u in urls)


def open_url(url: str) -> None:
    try:
        _http_json("/json/new?" + urllib.parse.quote(url, safe=""),
                   method="PUT")
    except Exception as e:
        print(f"tab-open: {url}: {e}", flush=True)


def _open_pending_start() -> None:
    """Spec 48: open a pending start URL queued while Chrome was down.

    The router asks us to open a capture surface (landing ?goto= or a
    session-page pill) before/while Chrome was starting; this runs after
    restore_tabs()/boot_restore() and opens it once, then clears it."""
    global _pending_start_url
    if not _pending_start_url:
        return
    url = _pending_start_url
    _pending_start_url = None
    if url in page_urls():
        print(f"tab-restore: pending start URL already open: {url}",
              flush=True)
        return
    open_url(url)
    print(f"tab-restore: pending start URL opened: {url}", flush=True)


def ensure_homepage() -> None:
    """S1 (2026-08-21): open the homepage only when the browser has ZERO
    real tabs (snapshot restore already covers the non-empty case).
    Spec 48: a pending start URL (router-requested surface) wins over the
    homepage — that is the whole point of the capture-surface UX.
    Spec 61 (2026-08-25): NEVER run while a restore/pending-start is
    still pending — the homepage must stay a zero-tabs fallback. If a
    restore is in flight, defer the homepage decision until it finishes
    (it re-checks); the homepage must never join a restored tab set and
    push it over TAB_LIMIT (tab-loss incidents 58/61)."""
    if _need_restore or _pending_start_url:
        print("tab-restore: homepage deferred (restore/pending in flight)",
              flush=True)
        threading.Thread(target=_homepage_after_restore, daemon=True).start()
        return
    if page_urls():
        return
    if _pending_start_url:
        _open_pending_start()
        return
    open_url(HOME_URL)
    print(f"tab-restore: zero tabs -> opened homepage {HOME_URL}", flush=True)


def _homepage_after_restore() -> None:
    """Spec 61: delayed homepage decision after a restore finished — only
    opens when the browser is STILL at zero real tabs."""
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            with _restore_lock:
                if not _need_restore and not _pending_start_url:
                    break
        except Exception:
            pass
        time.sleep(2)
    try:
        if not _need_restore and not _pending_start_url and not page_urls():
            open_url(HOME_URL)
            print(f"tab-restore: zero tabs (post-restore) -> opened homepage "
                  f"{HOME_URL}", flush=True)
    except Exception as e:
        print(f"tab-restore: deferred homepage failed: {e}", flush=True)


def restore_tabs() -> None:
    """D5: re-open snapshot tabs after a Chrome (re)start; close newtab.
    S4: restore is capped at TAB_LIMIT. S1: if nothing ends up open
    (no snapshot), fall back to the homepage."""
    global _restore_done
    with _restore_lock:
        if _restore_done:
            # Spec 61: a restore already ran for this Chrome start — do
            # not re-open the snapshot into an already-restored browser
            # (a duplicate pass only multiplies tabs and feeds eviction).
            return
        for _ in range(24):  # wait up to ~2 min for CDP
            if cdp_ok():
                break
            time.sleep(5)
        time.sleep(10)  # let Chrome settle + window-manager pin the window
        urls = load_snapshot()[:TAB_LIMIT]  # S4: cap restore at the limit
        if not urls:
            print("tab-restore: no snapshot — nothing to restore",
                  flush=True)
            _restore_done = True  # spec 61b: restore window over (nothing)
            ensure_homepage()
            return
        try:
            targets = _http_json("/json/list")
        except Exception as e:
            print(f"tab-restore: list failed: {e}", flush=True)
            _restore_done = True  # spec 61b: don't wedge snapshots forever
            return
        open_urls = {t.get("url") for t in targets if t.get("type") == "page"}
        opened = 0
        for u in urls:
            if u in open_urls:
                continue
            try:
                _http_json("/json/new?" + urllib.parse.quote(u, safe=""),
                           method="PUT")
                opened += 1
                time.sleep(1.5)  # let the tab boot before the next one
            except Exception as e:
                print(f"tab-restore: open {u}: {e}", flush=True)
        if opened:
            try:
                for t in _http_json("/json/list"):
                    if t.get("type") == "page" and t.get("url") in EMPTY_URLS:
                        _http_text("/json/close/" + t["id"])
                        time.sleep(0.5)
            except Exception as e:
                print(f"tab-restore: close newtab: {e}", flush=True)
        print(f"tab-restore: opened {opened} tab(s) from snapshot", flush=True)
        _restore_done = True  # spec 61: this Chrome start is restored
        ensure_homepage()  # S1: no-op when the restore left tabs open
        _open_pending_start()  # spec 48: router-requested surface wins


def boot_restore() -> None:
    """D5: after a container recreate / process boot, restore if the
    browser came up at an empty state (native restore never fires).
    S1: with no snapshot and zero tabs, open the homepage."""
    global _restore_done  # spec 61b: assignments below MUST hit the module global
    if not load_snapshot():
        for _ in range(24):
            if cdp_ok():
                break
            time.sleep(5)
        time.sleep(10)
        _restore_done = True  # spec 61b: boot restore window over
        ensure_homepage()
        return
    for _ in range(24):
        if cdp_ok():
            break
        time.sleep(5)
    time.sleep(10)
    urls = page_urls()
    if all_empty(urls):
        print("tab-restore: boot restore (browser at empty state)", flush=True)
        restore_tabs()  # sets _restore_done itself (all exit paths)
    else:
        print(f"tab-restore: boot skip — {len(urls)} tab(s) already present",
              flush=True)
        _restore_done = True  # spec 61b: tabs already present, window over
        _open_pending_start()  # spec 48: router-requested surface wins


def _chrome_main_pid() -> int | None:
    """W3: best-effort main Chrome PID via /proc (supervisord child)."""
    try:
        import glob
        for p in glob.glob("/proc/[0-9]*/cmdline"):
            try:
                with open(p, "rb") as f:
                    cl = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
                if "remote-debugging-port" in cl and "--type=" not in cl:
                    return int(p.split("/")[2])
            except Exception:
                continue
    except Exception:
        pass
    return None


def _chrome_main_pid_baseline() -> None:
    """W3: set the watchdog's Chrome PID baseline (called in main)."""
    global _chrome_pid_baseline
    _chrome_pid_baseline = _chrome_main_pid()


def watchdog_loop() -> None:
    global _need_restore, _chrome_pid_baseline, _suspended, _restore_done
    fails = 0
    while True:
        time.sleep(WATCHDOG_SECS)
        if _suspended:
            # Spec 29: a suspended slot must STAY suspended — the watchdog
            # would otherwise fight the reaper by restarting chrome.
            fails = 0
            continue
        # W3: PID change => Chrome was (re)started by someone else
        # (supervisord auto-restart, manual start, crash loop) — queue a
        # restore; it will no-op if tabs are already present.
        pid = _chrome_main_pid()
        if pid is not None and _chrome_pid_baseline is not None and pid != _chrome_pid_baseline:
            print(f"watchdog: chrome pid changed {_chrome_pid_baseline} -> {pid}, queueing restore",
                  flush=True)
            _need_restore = True
            _restore_done = False  # spec 61: new Chrome start, fresh restore
        _chrome_pid_baseline = pid
        if cdp_ok():
            if chrome_owns_profile():
                # Spec 61b: never snapshot until the restore for THIS
                # Chrome start has completed — mid-restore the tab list
                # is transient, and a snapshot then would freeze a
                # partial set (observed live: 3 tabs → 1).
                if _restore_done:
                    snapshot_tabs()
                if fails:
                    print(f"watchdog: CDP recovered after {fails} failures",
                          flush=True)
                    _need_restore = True
                fails = 0
                if _need_restore:
                    _need_restore = False
                    threading.Thread(target=restore_tabs, daemon=True).start()
            else:
                # Spec 42: the running chrome does not own the on-disk
                # profile — never snapshot from it (would write another
                # user's tabs) and never restore tabs into it. Wait for
                # the next wake, which stops chrome + restores the right
                # profile first.
                fails = 0
            continue
        fails += 1
        print(f"watchdog: CDP unresponsive ({fails}/{WATCHDOG_FAILS})",
              flush=True)
        if fails >= WATCHDOG_FAILS:
            print("watchdog: restarting google-chrome", flush=True)
            res = restart_chrome()
            print(f"watchdog: restart result {res}", flush=True)
            _need_restore = True
            fails = 0


def fleet_state() -> dict:
    """D9 fleet gate state. dev01: running = this viewer's browser."""
    running = 1 if cdp_ok() else 0
    cap = _fleet_cap_override if _fleet_cap_override is not None else MAX_RUNNING_BROWSERS
    saturated = running >= cap
    return {"running_browsers": running, "cap": cap, "saturated": saturated,
            "message": SATURATION_MSG.format(cap=cap) if saturated else None}


def fleet_request() -> dict:
    state = fleet_state()
    if state["saturated"]:
        return {"ok": False, "granted": False, "error": state["message"]}
    return {"ok": True, "granted": True, "running_browsers": state["running_browsers"],
            "cap": state["cap"]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[restart-api] {self.client_address[0]} {fmt % args}",
              flush=True)

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            progs = sup_status()
            self._json(200, {"ok": True, "programs": progs,
                             "cdp_ok": cdp_ok(),
                             "heals": _heals,
                             "tabs": page_urls(),
                             # Spec 45: router take-path isolation check.
                             "suspended": _suspended,
                             "user": slot_user(),
                             # Spec 77: owner-bound boot hint — router's
                             # sweep loop reads this on idle slots.
                             "pending_archive_owner":
                                 _boot_archive_owner_value})
        elif self.path == "/snapshot":
            snapshot_tabs()
            self._json(200, {"ok": True,
                             "snapshot": load_snapshot()})
        elif self.path == "/config":
            # Tabbar S5 (2026-08-21): MV3 can't read env vars — the
            # extension fetches this once at startup (host permission for
            # 127.0.0.1:9230 is already in the manifest).
            self._json(200, {"ok": True,
                             "homeUrl": HOME_URL,
                             "tabLimit": TAB_LIMIT})
        elif self.path == "/fleet":
            self._json(200, fleet_state())
        elif self.path == "/idle":
            # Spec 29: activity/idle state — polled by the tabbar content
            # script for the grace-countdown toast.
            self._json(200, idle_status())
        else:
            self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        global _fleet_cap_override
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            body = {}
        if self.path == "/restart":
            res = restart_chrome()
            if res["ok"]:
                threading.Thread(target=restore_tabs, daemon=True).start()
            self._json(200, res)
        elif self.path == "/fleet/request":
            res = fleet_request()
            self._json(200 if res["ok"] else 503, res)
        elif self.path == "/identify":
            # Spec 29: router pushes the sticky user onto this slot (the
            # reaper needs it to name the archive). Spec 29b: the push also
            # carries the slot index (hostname is an opaque container ID).
            user = body.get("user", "").strip().lower()
            if not user:
                self._json(400, {"ok": False, "error": "user required"})
                return
            set_slot_user(user, slot=body.get("slot"))
            # New assignments can land on a suspended slot whose title-proxy
            # was stopped by the reaper — bring the UI front back so the
            # request that follows actually reaches neko.
            try:
                st = sup_status().get(TITLE_PROXY_PROG)
                if st and "STOPPED" in st.upper():
                    subprocess.run([SUPERVISORCTL, "start", TITLE_PROXY_PROG],
                                   capture_output=True, timeout=30)
                    print(f"idle: title-proxy restarted for {user}",
                          flush=True)
            except Exception as e:
                print(f"idle: title-proxy ensure failed: {e}", flush=True)
            self._json(200, {"ok": True, "user": user})
        elif self.path == "/wake":
            # Spec 29: router wakes a returning user's archive onto this
            # slot (restore + start chrome + tab restore).
            user = body.get("user", "").strip().lower()
            if not user:
                self._json(400, {"ok": False, "error": "user required"})
                return
            res = do_wake(user)
            self._json(200 if res.get("ok") else 500, res)
        elif self.path == "/suspend":
            # Spec 29: manual/test suspend hook (same path as the reaper).
            res = do_suspend()
            self._json(200, {"ok": True, "user": slot_user(),
                             "suspended": _suspended})
        elif self.path == "/release":
            # Spec 32: the tab bar's Exit button — user-initiated release.
            # Same teardown as suspend, but the router archive is labelled
            # reason=released and the freed slot is re-offered to the queue
            # head by the router's reaper.
            do_suspend("released")
            self._json(200, {"ok": True, "user": slot_user(),
                             "reason": "released"})
        elif self.path == "/open-url":
            # Spec 48 (capture-surface UX): the ROUTER asks us to open a
            # surface in the kiosk Chrome — from a session-page pill
            # (/kiosk/open) or a landing-page ?goto=. If Chrome is up,
            # open the tab live; else queue it as the pending start URL,
            # consumed by the next restore_tabs()/boot_restore() pass.
            # The router whitelists; here we only sanity-check the shape.
            global _pending_start_url
            url = (body.get("url") or "").strip()
            if not url:
                self._json(400, {"ok": False, "error": "url required"})
                return
            if not (url.startswith("/")
                    or url.startswith("http://")
                    or url.startswith("https://")):
                self._json(400, {"ok": False, "error": "bad url"})
                return
            if cdp_ok():
                open_url(url)
                print(f"open-url: live open {url}", flush=True)
                self._json(200, {"ok": True, "opened": True})
            else:
                _pending_start_url = url
                print(f"open-url: CDP down — pending start URL {url}",
                      flush=True)
                self._json(200, {"ok": True, "opened": "pending"})
        elif self.path == "/restart-neko":
            # Spec 39: router /fleet/rescue → restart the neko app process
            # only (never the container, never Chrome) — profile + tabs
            # survive; only the wedged WebRTC/auth server is recycled.
            # The router's users map is authoritative: body.user is the user
            # the router believes is on THIS slot, so a stale/absent local
            # slot_user (identify push failed) must not block the rescue.
            # Refuse only on a CONFLICT: the local file names a different
            # live owner (stale router state → don't restart the wrong one).
            global _rescue_last
            local = slot_user()
            want = (body.get("user") or "").strip().lower()
            if local and want and local != want:
                self._json(409, {"ok": False,
                                 "error": f"slot owner is {local}, not {want}"})
                return
            if not local and not want:
                self._json(409, {"ok": False,
                                 "error": "idle slot — nothing to rescue"})
                return
            now = time.time()
            if now - _rescue_last < CB_RESET_COOLDOWN_S:
                self._json(429, {"ok": False, "error": "cooldown"})
                return
            res = restart_neko()
            if res.get("ok"):
                _rescue_last = now
            self._json(200 if res.get("ok") else 502, {
                "ok": res.get("ok"), "user": want or local,
                **({k: v for k, v in res.items() if k != "ok"})})
        elif self.path == "/fleet/test":
            # dev/test hook (D9 DoD: "temporarily set cap=1 → third browser
            # gets the clear message"). In-memory only; resets on restart.
            try:
                if body.get("clear"):
                    _fleet_cap_override = None
                    self._json(200, {"ok": True, "cap": MAX_RUNNING_BROWSERS,
                                     "note": "override cleared"})
                else:
                    cap = int(body["cap"])
                    if cap < 1:
                        raise ValueError
                    _fleet_cap_override = cap
                    self._json(200, {"ok": True, "cap": cap,
                                     "note": "dev override — resets on restart"})
            except Exception as e:
                self._json(400, {"ok": False, "error": f"bad body: {e}"})
        else:
            self._json(404, {"ok": False, "error": "not found"})


def main() -> None:
    global _boot_archive_owner_value
    threading.Thread(target=watchdog_loop, daemon=True).start()
    threading.Thread(target=boot_restore, daemon=True).start()
    threading.Thread(target=reaper_loop, daemon=True).start()
    threading.Thread(target=stream_guard_loop, daemon=True).start()
    # Spec 77 (2026-08-28): seed the owner-bound boot hint BEFORE the
    # chrome autostart races us. If the slot has no .slot-user.json but
    # SESSIONS_DIR carries a real archive, the hint goes non-null and the
    # router's sweep loop dispatches a /wake — the standard restore path
    # then wipes the profile, copies the archive, starts chrome, and
    # restores tabs. We deliberately do NOT call record_chrome_start here
    # so the isolation guard refuses to archive an ownerless chrome.
    _boot_archive_owner_value = _boot_archive_owner()
    # W3: PID baseline must reflect the CURRENT Chrome. Wait for Chrome to
    # be up (boot_restore does the same), then re-baseline; without this a
    # mid-restart first tick would misread the new pid as a change.
    for _ in range(24):
        if cdp_ok():
            break
        time.sleep(5)
    _chrome_main_pid_baseline()
    # Spec 42: on container boot the supervised chrome auto-starts — record
    # that it serves the persisted slot user so snapshots stay allowed.
    # Spec 77: do NOT record_chrome_start(None) — _started_for_user stays
    # None. The isolation guard in _do_suspend_impl then refuses to
    # archive any tabs while ownerless (chrome owns no profile). The
    # router's boot-hint sweep will overwrite this with the real owner
    # via /wake (which calls record_chrome_start(<owner>)).
    if slot_user():
        record_chrome_start(slot_user())
    srv = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    print(f"restart-api: listening on :{LISTEN_PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
