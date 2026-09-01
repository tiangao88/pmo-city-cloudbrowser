#!/bin/bash
# D11 — tooling-init: ensure xdotool + curl + jq exist (DoD D11 alternative:
# "start-script apt" — survives container recreate because it runs at every
# boot via supervisord one-shot BEFORE chrome starts).
#
# W1 baseline: xdotool was apt-installed ephemerally (lost on recreate).
# This script re-installs on every boot when missing. apt cache is
# container-ephemeral, so each recreate costs one apt pass (~10-30s),
# acceptable against a Chrome launch that waits on priority order.
#
# Supervisord: [program:tooling-init] priority=0 (before policy-init/chrome),
# startsecs=0, autorestart=false → one-shot per boot.

set -u

TOOLS="xdotool curl jq"
NEED=""
for t in $TOOLS; do
  command -v "$t" >/dev/null 2>&1 || NEED="$NEED $t"
done

if [ -z "$NEED" ]; then
  echo "tooling-init: all tools present ($TOOLS)"
  exit 0
fi

echo "tooling-init: installing:$NEED"
# The neko image ships a dl.google.com repo whose key is missing in the
# container (NO_PUBKEY FD533C07C264648F) — a broken repo makes apt-get
# update FAIL outright (W1 "not signed" warning, W2 D11: fatal). The distro
# Chrome it would install is never used (CfT 128 runs from the profile
# volume), so disable the repo for this pass.
for f in /etc/apt/sources.list.d/*.list; do
  [ -f "$f" ] || continue
  if grep -q dl.google.com "$f"; then
    mv "$f" "$f.disabled"
    echo "tooling-init: disabled google repo ($f)"
  fi
done
for i in 1 2 3; do
  if apt-get update -qq && apt-get install -y --no-install-recommends $NEED; then
    break
  fi
  echo "tooling-init: apt attempt $i failed, retrying in 5s"
  sleep 5
done

for t in $TOOLS; do
  if command -v "$t" >/dev/null 2>&1; then
    echo "tooling-init: $t OK ($(command -v "$t"))"
  else
    echo "tooling-init: $t MISSING after install"
  fi
done
exit 0
