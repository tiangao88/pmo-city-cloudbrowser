#!/bin/bash
# sso-creds-provision.sh — host-side credential provisioner for the D15 broker.
#
# v3 (2026-08-19): session-reuse design. Reads the gateway's live BW_SESSION
# from /proc (no login, no master password anywhere in this script) and runs
# `bw get item` with XDG_CONFIG_HOME isolated to /opt/data/bw-cli-state (never
# under /home/hermes/.hermes).
#
# Why not the REST API key (client_credentials)? Probed 2026-08-18/19:
#   - password grant: Vaultwarden 1.32+ rejects plaintext master passwords and
#     the 2026 bw SDK's client-side KDF hash is not the classic
#     PBKDF2->b64(sha256(mk)) (3 variants probed, all rejected).
#   - client_credentials: authenticates fine (with SDK device fields), but the
#     API key cannot DECRYPT — all cipher fields come back encrypted
#     ("2.<b64>|<b64>|<b64>"); only a user-key session (master-password
#     unlock) can read item values. Hence session reuse.
#   - Why not login fresh? Each login churns bw state; the gateway ALREADY
#     holds a live session — reuse is zero-login and state-quarantined.
#
# Fetches the kiosk SSO credentials and writes them base64-encoded into the
# viewer's scripts volume as a 0600 file the broker consumes (never plaintext
# on disk, never echoed). The file is UNSET (removed) on provisioning errors
# so the broker never acts on stale/partial creds.
# Print nothing on success (silent for cron).
set -u

ITEM="${D15_BW_ITEM:-cloudbrowser-w1-test}"
SSH_KEY="${D15_SSH_KEY:-/home/hermes/.hermes/home/.ssh/id_ed25519_mother01}"
VOL_DIR="/var/lib/docker/volumes/4guplgcrvug7l7h64m2cxkm1_scripts/_data"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-/opt/data/bw-cli-state}"

# 1. Read the gateway's live BW_SESSION (no login, no password)
GWPID=$(pgrep -f "hermes gateway run" | head -1)
if [ -z "$GWPID" ]; then
  echo "[d15-creds] ERROR: gateway not running (no session source)" >&2
  exit 2
fi
SESSION=$(tr '\0' '\n' < "/proc/$GWPID/environ" 2>/dev/null | grep "^BW_SESSION=" | cut -d= -f2-)
if [ -z "$SESSION" ]; then
  echo "[d15-creds] ERROR: gateway has no BW_SESSION (bw-session.sh failed at boot?)" >&2
  exit 2
fi

# 2. Fetch item (retry races), extract creds, base64 in memory
CREDS_B64=""
for attempt in 1 2 3; do
  CREDS_B64=$(timeout 30 bw get item "$ITEM" --session "$SESSION" 2>/dev/null \
    | python3 -c "
import json, os, sys, base64
item = json.load(sys.stdin)
login = item.get('login', {})
if not login.get('username') or not login.get('password'):
    raise SystemExit('missing fields')
print(base64.b64encode(json.dumps({'username': login['username'],
                                   'password': login['password']}).encode()).decode())
" 2>/dev/null)
  [ -n "$CREDS_B64" ] && break
  sleep 2
done
unset SESSION
if [ -z "$CREDS_B64" ]; then
  echo "[d15-creds] ERROR: item fetch/extract failed for $ITEM" >&2
  exit 2
fi

# 3. write 0600 b64 file into the viewer's scripts volume (visible in-container
#    at /etc/neko/supervisord/sso-creds.b64); remove on any failure.
# NB: ssh reads known_hosts from the PASSWD home (/opt/data/.ssh), not $HOME;
# /opt/data wipes on container recreate → self-heal with accept-new (only adds
# NEW host keys, never replaces changed ones — safe for this internal host).
SSH_ARGS="-i $SSH_KEY -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"
echo "$CREDS_B64" | ssh $SSH_ARGS root@mother01.on-ai.sbs \
  "umask 177; cat > $VOL_DIR/sso-creds.b64 && chmod 600 $VOL_DIR/sso-creds.b64 && echo OK"
RC=$?
unset CREDS_B64
if [ $RC -ne 0 ]; then
  ssh $SSH_ARGS root@mother01.on-ai.sbs "rm -f $VOL_DIR/sso-creds.b64" 2>/dev/null
  echo "[d15-creds] ERROR: write to volume failed" >&2
  exit 2
fi
exit 0
