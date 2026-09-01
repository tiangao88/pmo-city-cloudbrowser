#!/bin/bash
# Clear the stale MV3 service-worker script cache (v1.4.0 code served from
# profile cache despite v1.5.0 on disk) and restart Chrome per container.
set -e
for spec in "slot-1-okixw2fxnwn1lakxvxajodww:/home/neko/.config/google-chrome" \
            "slot-2-okixw2fxnwn1lakxvxajodww:/home/neko/.config/google-chrome" \
            "viewer-4guplgcrvug7l7h64m2cxkm1:/home/neko/.config/google-chrome-w1"; do
  c="${spec%%:*}"
  prof="${spec##*:}"
  echo "=== $c ==="
  docker exec "$c" supervisorctl stop google-chrome
  docker exec "$c" sh -c "rm -rf '$prof/Service Worker' '$prof/ScriptCache' && echo 'SW cache cleared: $(ls -d "$prof/Service Worker" "$prof/ScriptCache" 2>/dev/null | wc -l) leftover'"
  docker exec "$c" supervisorctl start google-chrome
  sleep 3
  docker exec "$c" supervisorctl status google-chrome
done
echo "ALL DONE"
