#!/bin/bash
# coolify-local.sh (working copy) — Coolify prod API from mother01 localhost.
# Token travels via stdin only (never argv/remote ps). known_hosts = /opt/data/.ssh.
# Usage: coolify-local.sh METHOD PATH [JSON_BODY_FILE]
SSH_KEY=/home/hermes/.hermes/home/.ssh/id_ed25519_mother01
KNOWN=/opt/data/.ssh/known_hosts
M=${1:-GET}; P=${2:-/api/v1/services}; BODY=${3:-}
TOK=$(tr '\0' '\n' < /proc/$(pgrep -f "hermes gateway" | head -1)/environ | sed -n 's/^COOLIFY_TOKEN_PROD=//p')
[ -z "$TOK" ] && { echo "no token" >&2; exit 1; }

if [ -n "$BODY" ]; then
  REMOTE='IFS= read -r TOK; curl -s -m 90 -X '"$M"' "http://localhost:8000'"$P"'" -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" --data-binary @-'
else
  REMOTE='IFS= read -r TOK; curl -s -m 90 -X '"$M"' "http://localhost:8000'"$P"'" -H "Authorization: Bearer $TOK"'
fi

{
  echo "$TOK"
  [ -n "$BODY" ] && cat "$BODY"
} | ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o UserKnownHostsFile="$KNOWN" \
    root@mother01.on-ai.sbs "$REMOTE"
