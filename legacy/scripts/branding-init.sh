#!/bin/bash
# branding-init: overlay Cloudbrowser branding over the neko static UI.
# Static UI lives inside the image at /var/www (not a volume), so this
# one-shot re-applies the overlay at every container start.
# Branding files live in the scripts volume (canonical in both repos),
# mounted read-only at /etc/neko/supervisord/branding.
#
# Pinned to neko 2.9.0 asset names:
#   - img/logo.<hash>.svg  (hash is the one the app bundle references;
#     changes on neko upgrade -> re-pin the filename here and in branding/)
#   - js/app.<hash>.js      (patched wordmark bundle; same re-pin rule)
#   - favicon-*, apple-touch-icon, android-chrome-*, mstile-*, manifest
set -e
SRC=/etc/neko/supervisord/branding
DEST=/var/www
IMG=/var/www/img
JS=/var/www/js
if [ ! -d "$SRC" ]; then
  echo "branding dir missing: $SRC (nothing to apply)"
  exit 0
fi
mkdir -p "$IMG" "$JS"
# top-level files -> /var/www ; logo.*.svg -> /var/www/img ; js/*.js -> /var/www/js
for f in "$SRC"/*; do
  [ -f "$f" ] || continue
  name=$(basename "$f")
  case "$name" in
    logo.*.svg) cp "$f" "$IMG/$name" ;;
    *)          cp "$f" "$DEST/$name" ;;
  esac
done
for f in "$SRC"/js/*; do
  [ -f "$f" ] || continue
  cp "$f" "$JS/$(basename "$f")"
done
chmod 644 "$DEST"/*.png "$DEST"/*.svg "$DEST"/site.webmanifest "$DEST"/browserconfig.xml "$IMG"/logo.*.svg "$JS"/*.js 2>/dev/null || true
echo "branding applied: $(basename -a "$SRC"/* "$SRC"/js/* 2>/dev/null | tr '\n' ' ')"
