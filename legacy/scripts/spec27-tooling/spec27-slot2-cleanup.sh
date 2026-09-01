#!/bin/bash
# slot-2 post-test cleanup: close extra tabs, keep one pmo.city, rewrite snapshot.
set -e
docker exec -i slot-2-okixw2fxnwn1lakxvxajodww python3 - <<'PYEOF'
import json, urllib.request, time
def get(p):
    with urllib.request.urlopen("http://127.0.0.1:9222" + p, timeout=5) as r:
        return json.load(r)
pages = get("/json/list")
to_close = [t["id"] for t in pages if t["type"] == "page" and "pmo.city" not in t["url"]]
# keep exactly one pmo.city
pmo = [t["id"] for t in pages if t["type"] == "page" and "pmo.city" in t["url"]]
to_close += pmo[1:]
for tid in to_close:
    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/close/" + tid, timeout=5).read()
        time.sleep(0.4)
    except Exception as e:
        print("close", tid, e)
time.sleep(1)
left = [t["url"] for t in get("/json/list") if t["type"] == "page"]
print("remaining pages:", left)
open("/home/neko/.config/google-chrome/tab-snapshot.json", "w").write(
    json.dumps({"ts": int(time.time()), "urls": left}))
print("snapshot rewritten:", left)
PYEOF
echo DONE
