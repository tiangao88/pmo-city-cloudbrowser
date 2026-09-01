#!/bin/bash
# spec27 restore pass v2 (runs ON mother01): clean snapshots for the slots,
# keep viewer's, then POST /restart on all three (proper restore path).
set -e

snap() { # snap <container> <profile> <urls-json>
  local c="$1" prof="$2" urls="$3"
  docker exec -i "$c" python3 - "$urls" <<'PYEOF'
import json, sys, time
urls = json.loads(sys.argv[1])
p = "/home/neko/.config/google-chrome/tab-snapshot.json"
if sys.argv[1].startswith("KEEP"):
    print("KEEP: snapshot untouched")
    sys.exit(0)
open(p, "w").write(json.dumps({"ts": int(time.time()), "urls": urls}))
print("snapshot ->", open(p).read())
PYEOF
}

restart_chrome() { # restart_chrome <container>
  docker exec -i "$1" python3 - <<'PYEOF'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:9230/restart", data=b"", timeout=20).read().decode())
PYEOF
}

echo "--- slot-1: clean snapshot (1 homepage) ---"
snap slot-1-okixw2fxnwn1lakxvxajodww /home/neko/.config/google-chrome '["https://pmo.city/"]'
echo "--- slot-2: clean snapshot (1 homepage) ---"
snap slot-2-okixw2fxnwn1lakxvxajodww /home/neko/.config/google-chrome '["https://pmo.city/"]'
echo "--- viewer: keep snapshot ---"
docker exec viewer-4guplgcrvug7l7h64m2cxkm1 python3 -c "import json;print('viewer snapshot:',open('/home/neko/.config/google-chrome-w1/tab-snapshot.json').read())"

for c in slot-1-okixw2fxnwn1lakxvxajodww slot-2-okixw2fxnwn1lakxvxajodww viewer-4guplgcrvug7l7h64m2cxkm1; do
  echo "--- $c: POST /restart ---"
  restart_chrome "$c"
done
echo ALL-DONE
