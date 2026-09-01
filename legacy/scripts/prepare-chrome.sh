#!/bin/sh
# W1/W2 reference viewer Chrome wrapper.
#
# Spec 72: use the same fail-closed, version-independent customization gate as
# fleet slots. Before EVERY launch this validates the dual-root managed policy,
# disables Chrome password/autofill storage, purges Login Data*, validates the
# tab-bar extension and records the actual browser/extension versions.
#
# The reference viewer deliberately preserves its prior D5 last-session
# behavior; fleet slots use fresh-session mode and router-owned snapshots.
set -eu

PROFILE=/home/neko/.config/google-chrome-w1
READY=/tmp/pmo-city-chrome-policy.ready
CFT_ROOT="$PROFILE"
CFT_CHROME_BIN="${CFT_CHROME_BIN:-$CFT_ROOT/cft-chrome-current/chrome}"

[ -f "$READY" ] || {
  echo "prepare-chrome: FATAL: mandatory policy init did not complete" >&2
  exit 1
}

# A CfT update should set CFT_CHROME_BIN or atomically repoint
# cft-chrome-current. The fallback keeps the currently seeded reference viewer
# working, but does not encode a version in this wrapper.
if [ ! -x "$CFT_CHROME_BIN" ]; then
  for candidate in "$CFT_ROOT"/cft-chrome-*/chrome; do
    if [ -x "$candidate" ]; then
      CFT_CHROME_BIN="$candidate"
      break
    fi
  done
fi
[ -x "$CFT_CHROME_BIN" ] || {
  echo "prepare-chrome: FATAL: no executable CfT binary" >&2
  exit 1
}

rm -f "$PROFILE/SingletonLock" "$PROFILE/SingletonSocket" "$PROFILE/SingletonCookie"

BROWSER_VERSION="$($CFT_CHROME_BIN --version 2>/dev/null)" || {
  echo "prepare-chrome: FATAL: cannot read CfT version" >&2
  exit 1
}
[ -n "$BROWSER_VERSION" ] || {
  echo "prepare-chrome: FATAL: empty CfT version" >&2
  exit 1
}

/usr/bin/python3 /etc/neko/supervisord/chrome-customize.py prepare-profile \
  --profile "$PROFILE" \
  --policy /etc/opt/chrome_for_testing/policies/managed/pmo-city-security.json \
  --extension /etc/neko/supervisord/tabbar-extension \
  --browser-version "$BROWSER_VERSION" \
  --restore-mode last-session

exec "$CFT_CHROME_BIN" --no-sandbox \
  --kiosk --disable-infobars --restore-last-session --window-position=0,0 --display="${DISPLAY:-:99}" \
  --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check --disable-session-crashed-bubble \
  --force-dark-mode --disable-gpu --disable-dev-shm-usage \
  --remote-debugging-address=0.0.0.0 --remote-debugging-port=9222 --remote-allow-origins='*' \
  --disable-extensions-except=/etc/neko/supervisord/tabbar-extension \
  --load-extension=/etc/neko/supervisord/tabbar-extension
