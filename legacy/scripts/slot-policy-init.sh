#!/bin/sh
# S7 fleet v2: install mandatory Chrome security policy on every container
# boot and repair profile ownership. Both official Chrome and official Chrome
# for Testing policy roots are populated so a CfT binary update cannot bypass
# PMO City controls. chrome-customize.py is the single source of truth.
set -eu

CUSTOMIZER=/etc/neko/supervisord/chrome-customize.py
READY=/tmp/pmo-city-chrome-policy.ready
rm -f "$READY"
if [ ! -r "$CUSTOMIZER" ]; then
  echo "slot-policy-init: FATAL: missing $CUSTOMIZER" >&2
  exit 1
fi

# Keep selected harmless baked policy values, but never inherit the image's
# extension lockdown. The PMO City managed file is installed separately.
P=/etc/opt/chrome/policies/managed/policies.json
if [ -f "$P" ]; then
  python3 - "$P" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, encoding="utf-8") as f:
    data = json.load(f)
for key in ("ExtensionInstallBlocklist", "ExtensionInstallAllowlist", "ExtensionInstallForcelist"):
    data.pop(key, None)
with open(p, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write("\n")
PY
  chmod 644 "$P"
fi

python3 "$CUSTOMIZER" install-policy \
  /etc/opt/chrome/policies/managed \
  /etc/opt/chrome_for_testing/policies/managed

# Chrome runs as uid 1000. Legacy root-owned profile files would make the
# customization fail or be ignored, so repair ownership before launch.
if command -v chown >/dev/null 2>&1; then
  chown -R neko:neko /home/neko/.config /home/neko/.cache 2>/dev/null || \
    echo "slot-policy-init: chown skipped (dirs absent or busy)"
fi

touch "$READY"
chmod 644 "$READY"
echo "slot-policy-init-ok"
