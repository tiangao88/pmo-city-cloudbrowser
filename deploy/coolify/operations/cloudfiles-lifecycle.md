# CloudFiles lifecycle and durable-volume operations

Audience: **operator only** (Coolify host / Docker access). This runbook covers
the Phase 4 operational guarantees for the CloudFiles product slice: the
internal `downloads` service owns the durable per-principal volume; the public
`cloudfiles` gateway never stores files itself.

Scope guard: every command below targets one explicit instance
(`CB_INSTANCE_ID`). Never run against an unqualified or default instance.
Phase 6 (live rollout, DNS, Traefik, TinyAuth) requires separate explicit
approval; this document does not grant it.

## Data layout and EU residency

- Durable volume: the compose `downloads` volume, mounted at
  `/data/downloads` inside the `downloads` container (instance-prefixed
  volume name `${CB_INSTANCE_ID}-downloads`).
- Owner areas: `/data/downloads/<sha256(principal)>/entries` (canonical) and
  `/data/downloads/<principal>/` (prior compatibility layout, reads only).
  Quarantine: `<owner>/quarantine`. Metadata index: `<owner>/.index.json`.
- Residency assertion: the Coolify host for the CloudBrowser deployment
  (`mother01`) is located in the European Union; client file data never
  leaves that host or its EU-backed volume. Re-assert the host region before
  any migration or volume move; a migration that changes residency requires
  operator sign-off.
- The gateway and downloads containers run as non-root `cloudbrowser`
  (uid 10001). The durable volume must stay owned by uid 10001.

## Guarantees enforced in code (Phase 4)

- Quota: 5 GB per principal, enforced before publication in the durable
  store (`DownloadStore.quota_bytes`). Oversize attempts raise and never
  become retrievable.
- Retention: 90 days. `DownloadsService.purge_expired` deletes retrievable
  entries older than the cutoff and returns only a redacted count for audit.
  Quarantine is never purged by the retention sweep.
- GDPR erasure: `erase_principal` removes the canonical hashed owner root and
  the prior raw-principal root idempotently (a second run is a no-op) and
  emits a redacted `erasure.completed` audit event (hashes only).
- Scanning: the ClamAV adapter (`ClamAvScanner`) speaks clamd INSTREAM over
  TCP and fails closed: any non-clean, malformed, oversized, or unreachable
  result is treated as quarantined, never published.
- Quarantine notification: bounded redacted events (`request_id`,
  `principal_hash`, `name_hash`, `size`, `sha256`) — no raw identity, path,
  or filename ever leaves the pipeline (threat T14).
- Metrics/readiness: bounded counters (ingest count/bytes) and `/ready` gate
  on the internal downloads dependency. There is intentionally no public
  `/metrics` route (the public surface rejects it).

## Retention sweep (90-day purge)

Run inside the `downloads` container as the service user:

```bash
docker exec <downloads-container> python3 - <<'PY'
from pathlib import Path
from datetime import datetime, timezone, timedelta
from cloudbrowser.downloads.service import DownloadsService
from cloudbrowser.cloudfiles.retention import RetentionJanitor, purge_summary

service = DownloadsService(store_root=Path("/data/downloads"))
janitor = RetentionJanitor(retention_days=90)
cutoff = datetime.now(timezone.utc) - timedelta(days=90)
# Enumerate principals from the volume (hashed and prior roots):
roots = sorted(p for p in Path("/data/downloads").iterdir() if p.is_dir())
for root in roots:
    principal = root.name  # hashed key or raw principal (prior layout)
    removed = service.purge_expired(principal, older_than=cutoff)
    if removed:
        print(principal, purge_summary(removed))  # count only, no names
PY
```

Dry-run first by replacing `service.purge_expired(...)` with a read-only
listing (`list_entries`) and printing only counts. Never log raw filenames:
audit records carry counts and hashes only.

## Quota check

```bash
docker exec <downloads-container> python3 - <<'PY'
from pathlib import Path
from cloudbrowser.downloads.service import DownloadsService
s = DownloadsService(store_root=Path("/data/downloads"))
for principal in ("owner-a@example.test",):
    print(s.usage_bytes(principal))  # bytes, compared against 5 GB quota
PY
```

## GDPR erasure (principal deletion)

Erasure is idempotent and redacted:

```bash
docker exec <downloads-container> python3 - <<'PY'
from pathlib import Path
from cloudbrowser.cloudfiles.erasure import erase_principal
print(erase_principal(principal="owner-a@example.test",
                      store_root=Path("/data/downloads"),
                      request_id="ops-<run-id>"))
PY
```

Verify: the owner directory is gone under both layouts and
`GET /api/files` for that principal returns an empty list after the gateway
binding is re-issued.

## Backup and restore (durable volume)

Backup (host side, instance-qualified volume name):

```bash
docker run --rm \
  -v "${CB_INSTANCE_ID}-downloads":/data/downloads:ro \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/cloudfiles-${CB_INSTANCE_ID}-$(date +%F).tar.gz \
    -C /data downloads
```

Restore to a **stopped** downloads container (never live-write):

```bash
docker run --rm \
  -v "${CB_INSTANCE_ID}-downloads":/data/downloads \
  -v "$(pwd)":/backup \
  alpine tar xzf /backup/cloudfiles-${CB_INSTANCE_ID}-<date>.tar.gz \
    -C /data downloads
# Fix ownership after restore:
docker run --rm -v "${CB_INSTANCE_ID}-downloads":/data/downloads \
  alpine chown -R 10001:10001 /data/downloads
```

Backup policy: daily backup, weekly restore drill, quarterly erasure spot
check. A restore must be verified by listing one principal's files and
downloading one attachment through the gateway before the volume is declared
healthy.

## Failure modes (fail closed, no data leak)

- Downloads dependency unreachable → gateway `/ready` 503; owner routes fail
  closed with bounded errors (no raw paths or identities in responses).
- Scanner unreachable/error → ingest quarantines (never publishes).
- Quota exceeded → file is not published; usage unchanged.
- Erasure on a missing principal → successful no-op (idempotent).

## Change log

- 2026-09-04: Phase 4 runbook (quota, retention, erasure, ClamAV adapter,
  quarantine notifications, backup/restore, EU residency assertion).
