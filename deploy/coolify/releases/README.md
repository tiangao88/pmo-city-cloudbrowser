# Release manifests

Each release directory contains the exact product/specification/contract
combination and installation namespace. A manifest is installable only when
its images are pinned, health checks exist, migration/rollback are tested, and
its security gates pass.

The `v0.1.0` directory is a deliberately non-installable migration marker.
The current Coolify image bundle still uses the prior published digest pins;
this working tree is a pre-build source/spec checkpoint, so those pins are
retained for provenance only and are not evidence for the current source. The
release manifest is intentionally `status: pre-build-not-installable` with
`installable: false`, `sourceState: pending-build`, and
`imageState: stale-pre-change`.

The sequence remains: commit the source/spec change, have the user/operator
trigger the approved GitHub Actions build from that commit, verify
provenance/SBOM, synchronize the immutable digests in a separate release
change, and run the provenance/full gates. Deployment and live qualification
require separate approval after those steps.

## Grant custody state lifecycle

The broker state volume contains the versioned owner-only
`grant-custody-v1.sqlite3` database. The legacy `/data/state/grants.sqlite3`
path and `grants` table are not accepted by the runtime. Custody metadata is
explicitly versioned as `cloudbrowser.grant-custody.v1`/version `1`; missing or
unsupported metadata fails closed.

Use the offline operator CLI for an existing volume. It backs up legacy rows
but never infers them into two-leg per-user grants, because the old records lack
both custody legs:

```bash
python -m cloudbrowser.credential_broker.grant_admin migrate-legacy \
  --source /data/state/grants.sqlite3 \
  --destination /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/grants.legacy.backup.sqlite3 \
  --kek-hex "$GRANT_KEK_HEX" --operator-id '<operator>'
```

The result is `reprovision_required` with `migrated: 0`; provision each current
immutable binding explicitly. For rollback, stop the broker, take a consistent
backup, and atomically restore a validated v1 backup. The current database is
saved first and rows are never merged across principals:

```bash
python -m cloudbrowser.credential_broker.grant_admin backup \
  --db /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/backups/grant-custody-v1.before.sqlite3
python -m cloudbrowser.credential_broker.grant_admin rollback \
  --db /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/backups/grant-custody-v1.before.sqlite3 \
  --current-backup /data/state/backups/grant-custody-v1.failed.sqlite3
```


1. Commit the source/spec change and record the source commit.
2. Have the user/operator trigger the approved GitHub Actions build from that
   commit; current token limits prevent an automatic trigger.
3. After CI passes, verify provenance/SBOM and synchronize immutable image
   digests in the compose, manifest, qualification records, and provenance
   tests as a separate release change.
4. Run the provenance and full gates against the synchronized pins.
5. Only then request deployment and live/closed-shadow qualification approval.

Do not edit stale image pins during a source/spec status checkpoint.
