#!/bin/bash
# spec27 rollout: slot-2 (clear junk snapshot -> homepage) + viewer (keep snapshot -> capped restore)
set -e
echo "=== slot-2: clear junk snapshot ==="
docker exec slot-2-okixw2fxnwn1lakxvxajodww sh -c 'rm -f /home/neko/.config/google-chrome/tab-snapshot.json && echo cleared'
echo "=== slot-2 restart chrome ==="
docker exec slot-2-okixw2fxnwn1lakxvxajodww python3 -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:9230/restart",data=b"",timeout=20).read().decode())'
echo "=== viewer restart chrome (snapshot kept) ==="
docker exec viewer-4guplgcrvug7l7h64m2cxkm1 python3 -c 'import urllib.request;print(urllib.request.urlopen("http://127.0.0.1:9230/restart",data=b"",timeout=20).read().decode())'
