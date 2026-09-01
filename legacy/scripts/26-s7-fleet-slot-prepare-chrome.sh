#!/bin/sh
# S7 fleet v2 SLOT chrome wrapper — version-independent CfT + kiosk + CDP.
# Canonical: cloud-browser-service/scripts/26-s7-fleet-slot-prepare-chrome.sh
#
# Spec 72 (2026-08-25): mandatory Chrome security customizations are applied
# before EVERY launch. The wrapper discovers the selected CfT binary without a
# version-hardcoded exec path, validates official CfT managed policy, disables
# Chrome password storage/autofill, purges legacy Login Data, validates the
# tab-bar extension and writes a browser/extension customization receipt.
# Any failure is fatal: an uncustomized embedded browser never starts.
#
# Real-case CDP (2026-08-20, Tigo go): slots must be agent-controllable.
# Stock Chrome 133 CDP was broken; the currently qualified build is CfT
# 128.0.6613.137. A later CfT is not accepted until the spec-72 update gate
# (CDP + kiosk + tabbar + policy + snapshot smoke) passes.
# --kiosk + --disable-infobars hide the "Chrome for Testing" notice bar
# (verified in kiosk it does not render); the tabbar-extension replaces the
# hidden native tab strip for humans.
#
# Steps:
#  1. Clear stale Singleton locks (abrupt kills leave locks owned by
#     "another computer" -> chrome exits FATAL).
#  2. Run chrome-customize.py BEFORE exec: validate official CfT managed
#     policy + tab-bar manifest; disable password storage/autofill; purge
#     legacy Login Data; enforce fresh-session/Translate prefs; record the
#     actual browser + extension versions.
#  3. exec the selected Chrome for Testing binary with CDP on 9222
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
POLICY_READY=/tmp/pmo-city-chrome-policy.ready
if [ ! -f "$POLICY_READY" ]; then
  echo "slot-prepare-chrome: FATAL: mandatory policy init did not complete" >&2
  exit 1
fi
CFT_ROOT=/home/neko/.config
CFT_CHROME_BIN="${CFT_CHROME_BIN:-$CFT_ROOT/cft-chrome-current/chrome}"
# Backward-compatible discovery for the currently seeded fleet. A CfT update
# should set CFT_CHROME_BIN or atomically repoint cft-chrome-current; neither
# path contains a browser version in this wrapper.
if [ ! -x "$CFT_CHROME_BIN" ]; then
  for candidate in "$CFT_ROOT"/cft-chrome-*/chrome; do
    if [ -x "$candidate" ]; then
      CFT_CHROME_BIN="$candidate"
      break
    fi
  done
fi
if [ ! -x "$CFT_CHROME_BIN" ]; then
  echo "slot-prepare-chrome: FATAL: no executable CfT binary" >&2
  exit 1
fi

rm -f "$PROFILE/SingletonLock" "$PROFILE/SingletonSocket" "$PROFILE/SingletonCookie"

# Derive the Chrome window size from NEKO_SCREEN (WxH[@fps]); fall back
# to 1280x720 if unset or malformed.
NEKO_SCREEN="${NEKO_SCREEN:-1280x720@30}"
WIN_W="${NEKO_SCREEN%%x*}"
WIN_H="${NEKO_SCREEN#*x}"; WIN_H="${WIN_H%%@*}"
[ -n "$WIN_W" ] || WIN_W=1280
[ -n "$WIN_H" ] || WIN_H=720

BROWSER_VERSION="$($CFT_CHROME_BIN --version 2>/dev/null)" || {
  echo "slot-prepare-chrome: FATAL: cannot read CfT version" >&2
  exit 1
}
/usr/bin/python3 /etc/neko/supervisord/chrome-customize.py prepare-profile \
  --profile "$PROFILE" \
  --policy /etc/opt/chrome_for_testing/policies/managed/pmo-city-security.json \
  --extension /etc/neko/supervisord/tabbar-extension \
  --browser-version "$BROWSER_VERSION"

exec "$CFT_CHROME_BIN" --no-sandbox \
  --kiosk --disable-infobars --window-size=${WIN_W},${WIN_H} --window-position=0,0 --display="${DISPLAY:-:99}" \
  --user-data-dir="$PROFILE" --no-first-run --force-dark-mode \
  --disable-gpu --remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 \
  --remote-allow-origins='*' --disable-dev-shm-usage \
  --load-extension=/etc/neko/supervisord/tabbar-extension
