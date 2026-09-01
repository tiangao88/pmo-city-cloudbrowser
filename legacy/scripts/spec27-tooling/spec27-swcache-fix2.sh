#!/bin/bash
# Correct SW script cache clear: $PROFILE/Default/Service Worker (per-partition).
# The root-level "Service Worker" dir is vestigial; the real script cache is
# under Default/. Fixes stale MV3 SW code after background.js updates.
set -e
for spec in "slot-1-okixw2fxnwn1lakxvxajodww:/home/neko/.config/google-chrome" \
            "slot-2-okixw2fxnwn1lakxvxajodww:/home/neko/.config/google-chrome" \
            "viewer-4guplgcrvug7l7h64m2cxkm1:/home/neko/.config/google-chrome-w1"; do
  c="${spec%%:*}"
  prof="${spec##*:}"
  echo "=== $c ==="
  docker exec "$c" supervisorctl stop google-chrome
  docker exec "$c" sh -c "rm -rf '$prof/Default/Service Worker' && echo 'cleared: '$prof/Default/Service Worker"
  docker exec "$c" supervisorctl start google-chrome
  sleep 3
  docker exec "$c" supervisorctl status google-chrome
done
echo ALL-DONE
