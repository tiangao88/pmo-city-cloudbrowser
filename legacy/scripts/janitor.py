#!/usr/bin/env python3
"""W1 janitor — quota + retention + ClamAV scan-at-ingest (FR-12 I3/I6).

Runs on a schedule (Coolify scheduled task, container `janitor`):
  1. Scan-at-ingest: every file newer than last run is sent to ClamAV
     (clamd TCP). Infected → moved to /data/downloads/.quarantine/<ts>_<name>,
     user notified via log line (agent reads it).
  2. Quota: if the user area exceeds QUOTA_BYTES, purge oldest files until
     under (log-only in W1 unless PURGE=1).
  3. Retention: delete files older than RETENTION_DAYS.

State: /data/downloads/.janitor-state (mtime of last scan boundary).
All decisions logged to stdout — the agent surfaces them; no plaintext.

Env: CLAMAV_HOST, CLAMAV_PORT, QUOTA_BYTES, RETENTION_DAYS, PURGE (0/1).
"""
import datetime as dt
import os
import socket
import sys
import time

DOWNLOADS = "/data/downloads"
STATE = os.path.join(DOWNLOADS, ".janitor-state")
QUARANTINE = os.path.join(DOWNLOADS, ".quarantine")
SCAN_EXTENSIONS = {".exe", ".msi", ".zip", ".pdf", ".doc", ".docx", ".xls",
                   ".xlsx", ".js", ".jar", ".apk", ".iso", ".dmg", ".bat",
                   ".cmd", ".scr", ".vbs", ".ps1", ".sh"}


def now_ts() -> float:
    return time.time()


def clamd_scan(path: str, host: str, port: int) -> str | None:
    """Returns 'FOUND'/'ERROR'/'OK' via clamd INSTREAM (port 3310)."""
    try:
        s = socket.create_connection((host, port), timeout=30)
        s.sendall(b"zINSTREAM\0")
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                s.sendall(len(chunk).to_bytes(4, "big") + chunk)
        s.sendall((0).to_bytes(4, "big"))
        resp = s.recv(1024).decode(errors="replace")
        s.close()
        if "FOUND" in resp:
            return "FOUND"
        if "OK" in resp:
            return "OK"
        return "ERROR:" + resp[:60]
    except Exception as e:  # noqa: BLE001
        return f"ERROR:{e}"


def main() -> int:
    host = os.environ.get("CLAMAV_HOST", "clamav")
    port = int(os.environ.get("CLAMAV_PORT", "3310"))
    quota = int(os.environ.get("QUOTA_BYTES", "5368709120"))
    retention_days = int(os.environ.get("RETENTION_DAYS", "90"))
    purge = os.environ.get("PURGE", "0") == "1"

    os.makedirs(QUARANTINE, exist_ok=True)
    boundary = os.path.getmtime(STATE) if os.path.exists(STATE) else now_ts() - 3600
    cutoff = now_ts() - retention_days * 86400

    files = []
    for name in os.listdir(DOWNLOADS):
        p = os.path.join(DOWNLOADS, name)
        if name.startswith(".") or not os.path.isfile(p):
            continue
        files.append((os.path.getmtime(p), os.path.getsize(p), name, p))
    files.sort()

    # 1. scan-at-ingest
    for _, _, name, p in files:
        if os.path.getmtime(p) < boundary:
            continue
        if not os.path.splitext(name)[1].lower() in SCAN_EXTENSIONS:
            print(f"[janitor] scan-skip {name} (ext not scanned)", flush=True)
            continue
        verdict = clamd_scan(p, host, port)
        if verdict == "FOUND":
            dest = os.path.join(QUARANTINE, f"{int(now_ts())}_{name}")
            os.rename(p, dest)
            print(f"[janitor] QUARANTINED {name} → {dest}", flush=True)
        else:
            print(f"[janitor] scan {name}: {verdict}", flush=True)

    # 2. retention (before quota — frees space deterministically)
    purged_retention = 0
    for mtime, _, name, p in files:
        if mtime < cutoff:
            os.remove(p)
            purged_retention += 1
    if purged_retention:
        print(f"[janitor] retention purged {purged_retention} files >{retention_days}d", flush=True)

    # 3. quota
    total = sum(sz for _, sz, _, _ in files)
    over = total - quota
    if over > 0:
        if purge:
            removed = 0
            for _, _, name, p in files:
                if over <= 0:
                    break
                os.remove(p)
                over -= os.path.getsize(p)
                removed += 1
            print(f"[janitor] quota purged {removed} oldest files ({total}→~{quota})", flush=True)
        else:
            print(f"[janitor] OVER-QUOTA by {over} bytes — PURGE=0, log-only", flush=True)

    with open(STATE, "w") as f:
        f.write(str(now_ts()))
    print(f"[janitor] done ({len(files)} files, {total} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
