#!/bin/sh
# S7 fleet v2 SLOT chrome wrapper — CfT 128 + kiosk + CDP (agent + human).
# Canonical: cloud-browser-service/scripts/26-s7-fleet-slot-prepare-chrome.sh
#
# Real-case CDP (2026-08-20, Tigo go): slots must be agent-controllable.
# Stock Chrome 133 CDP is broken (page-WS hang + -32001, proven by
# cdp-probe.py); CfT 128.0.6613.137 is CDP-verified (same as the W1 viewer).
# --kiosk + --disable-infobars hide the "Chrome for Testing" notice bar
# (verified in kiosk it does not render); the tabbar-extension replaces the
# hidden native tab strip for humans.
#
# Steps:
#  1. Clear stale Singleton locks (abrupt kills leave locks owned by
#     "another computer" -> chrome exits FATAL).
#  2. Patch Preferences BEFORE exec (profile volume persists, Chrome
#     rewrites it on exit):
#       - session.restore_on_startup=5  (fresh start, not "continue where
#         you left off" — see kiosk-window note below)
#       - translate.enabled=false       (no auto-translate popup)
#  3. exec Chrome for Testing 128 with CDP on 9222 (loopback) +
#     remote-allow-origins for browser-use. The cdp-relay program
#     (cdp-relay.py) exposes 0.0.0.0:9223 -> 127.0.0.1:9222 for external
#     agent access. NO startup URL (spec 27 S1, 2026-08-21): the homepage
#     is opened by restart-api only when the browser has zero real tabs
#     (snapshot restore covers the non-empty case) — the old hardcoded
#     launch URL added a homepage tab on every start / Relaunch.
#
# Kiosk-window sizing (2026-08-21): kiosk + --restore-last-session
# (restore_on_startup=1) restored the PREVIOUS session's window geometry
# (e.g. 945x1060 at top-left on a 1920x1080 desktop) — user saw a small
# window + black void (screenshot evidence, 26-s7-fleet-app.md). Fix:
# explicit --window-size (insurance even if kiosk geometry is ignored) +
# restore_on_startup=5 (fresh start; homepage handled by restart-api,
# see S1 above). Staged 2026-08-21; applied 2026-08-21.
# 2026-08-21 (D17 tuning): window MUST track the neko display
# (NEKO_SCREEN, default 1280x720@30) — a 1920x1080 window on a 1280x720
# desktop overflows and clips the tab bar / page edges (Tigo report).
PROFILE=/home/neko/.config/google-chrome

rm -f "$PROFILE/SingletonLock" "$PROFILE/SingletonSocket" "$PROFILE/SingletonCookie"

# Derive the Chrome window size from NEKO_SCREEN (WxH[@fps]); fall back
# to 1280x720 if unset or malformed.
NEKO_SCREEN="${NEKO_SCREEN:-1280x720@30}"
WIN_W="${NEKO_SCREEN%%x*}"
WIN_H="${NEKO_SCREEN#*x}"; WIN_H="${WIN_H%%@*}"
[ -n "$WIN_W" ] || WIN_W=1280
[ -n "$WIN_H" ] || WIN_H=720

/usr/bin/python3 - <<'PYEOF'
import json, os
p = "/home/neko/.config/google-chrome/Preferences"
d = json.load(open(p)) if os.path.exists(p) else {}
d.setdefault("session", {})["restore_on_startup"] = 5
d.setdefault("translate", {})["enabled"] = False
json.dump(d, open(p, "w"))
PYEOF

exec /home/neko/.config/cft-chrome-128/chrome --no-sandbox \
  --kiosk --disable-infobars --window-size=${WIN_W},${WIN_H} --window-position=0,0 --display="${DISPLAY:-:99}" \
  --user-data-dir="$PROFILE" --no-first-run --force-dark-mode \
  --disable-gpu --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 \
  --remote-allow-origins='*' --disable-dev-shm-usage \
  --load-extension=/etc/neko/supervisord/tabbar-extension
