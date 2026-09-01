#!/usr/bin/env python3
"""D8 — janitor loop: run janitor.py every JANITOR_INTERVAL seconds.

Makes scan-at-ingest REAL (previously the janitor container only slept —
scanning was triggered manually). The janitor container mounts the scripts
volume at /data/scripts:ro; compose command becomes:

    python /data/scripts/janitor-loop.py

Each tick invokes janitor.py in-process (same container, same env:
CLAMAV_HOST/CLAMAV_PORT/QUOTA_BYTES/RETENTION_DAYS/PURGE). Log lines are
prefixed [janitor-loop]; janitor.py output passes through unchanged so the
agent's notification surface ("user notified via log line") keeps working.
"""
import os
import subprocess
import sys
import time

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "janitor.py")
INTERVAL = int(os.environ.get("JANITOR_INTERVAL", "60"))

print(f"janitor-loop: every {INTERVAL}s → {SCRIPT}", flush=True)

while True:
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, SCRIPT])
        if r.returncode != 0:
            print(f"[janitor-loop] janitor.py exited {r.returncode}", flush=True)
    except Exception as e:
        print(f"[janitor-loop] error: {e}", flush=True)
    elapsed = time.time() - t0
    time.sleep(max(1, INTERVAL - elapsed))
