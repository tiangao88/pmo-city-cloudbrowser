#!/bin/bash
# cb-normalize-volume.sh — normalize the cb-fleet scripts volume so every
# file is readable by the app user (neko, uid 1000).
#
# WHY: the CloudBrowser app runs as non-root neko (uid 1000), but deploys
# land files as root. A file that is root-owned AND not world-readable
# (e.g. mode 640 from a `cat > file` write under umask 027) breaks the app
# silently: Chrome shows "Error Loading Extension: could not load
# javascript 'content.js'" because it cannot read the extension scripts.
#
# This script makes the volume safe regardless of how files were written:
#   - chown to uid 1000 (neko owns its own files -> readable by the app
#     no matter the mode; root-run processes still read anything)
#   - chmod a+rX (world-readable + traverse dirs; belt and suspenders)
#   - verify: fail loudly if any file remains unreadable
#
# Triggered by cb-normalize.timer (every 60 s) so ANY future write to the
# volume self-heals within a minute — no deploy step can wedge the browser
# again.
set -u

V=/var/lib/docker/volumes/okixw2fxnwn1lakxvxajodww_scripts/_data
if [ ! -d "$V" ]; then
  logger -t cb-normalize "volume $V missing"
  exit 1
fi

chown -R 1000:1000 "$V" || logger -t cb-normalize "chown failed rc=$?"
chmod -R a+rX "$V" || logger -t cb-normalize "chmod failed rc=$?"
chmod 755 "$V"

BAD=$(find "$V" -type f ! -perm -o+r | wc -l)
if [ "$BAD" -ne 0 ]; then
  logger -t cb-normalize "WARNING: $BAD unreadable file(s) remain in $V"
  exit 2
fi

logger -t cb-normalize "volume normalized ok"
exit 0
