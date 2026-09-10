# GrantHub two-leg custody and offline provisioning

Status: **implemented in source; runtime wiring requires the operator KEK and
is intentionally fail-closed until provisioned**. This closes the production
blocker without introducing a network GrantHub admin API or using live secrets.

## Contract

A grant is keyed by the complete immutable tuple:

```text
profile_id / principal_id / site_id / target_tab_id / browser_id / generation
```

The caller's email is never a lookup key. `CustodyGrantStore` stores an opaque
`grantref:v1.*` authorization reference and two independently authenticated
wrapped legs:

1. the 64-byte Vaultwarden user vault key;
2. the Vaultwarden refresh-token/session leg.

A random per-grant `K_user` wraps both legs. `K_user` is itself wrapped by a
32-byte broker key-encryption key (KEK). The KEK is supplied at startup or by
the offline operator command and is never stored in SQLite. The database holds
only ciphertext, nonces, tags, immutable binding metadata, an authorization
epoch, and redacted audit rows. It contains no master password, plaintext vault
key, refresh token, or access token.

Provision and revoke use `BEGIN IMMEDIATE` transactions. Revoke clears all
wrapped legs and increments the epoch atomically. A broker checkout rechecks
`active + epoch + full binding` before mint, before sync, before rotating the
refresh leg, before decrypting the selected item, and before returning material.
A refresh rejection invalidates the grant. Lease references are wiped
best-effort on scope exit.

## Versioned database lifecycle, migration, backup, and rollback

The runtime database is **not** `/data/state/grants.sqlite3`. That filename is
reserved for the historical authorization table and is rejected at startup.
The production path is:

```text
/data/state/grant-custody-v1.sqlite3
```

The custody database contains `grant_metadata` with schema id
`cloudbrowser.grant-custody.v1` and version `1`. Missing metadata, a legacy
`grants` table, an unknown schema id/version, or a malformed database causes
startup to fail closed; the process never creates a new table beside or over an
unknown database and never silently discards old rows.

### Offline migration from the old `grants` table

Old rows contain only a global/item reference and authorization fields. They do
not contain the two custody legs or the complete per-user custody proof. It is
therefore unsafe to infer a new active grant, even when profile/principal fields
look compatible. Migration is backup-only and creates an empty v1 custody DB;
every user must be explicitly reprovisioned with fresh two-leg material:

```bash
umask 077
python -m cloudbrowser.credential_broker.grant_admin migrate-legacy \
  --source /data/state/grants.sqlite3 \
  --destination /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/grants.legacy.$(date +%Y%m%d%H%M%S).sqlite3 \
  --kek-hex "$GRANT_KEK_HEX" \
  --operator-id '<audited operator id>'
```

The command reports `reprovision_required`, `migrated: 0`, and the legacy row
count. It does not copy, activate, or delete any legacy record. Verify the
backup before retaining it, then provision each current immutable binding with
`provision` below. Do not point the broker at the old path.

### Backup and rollback

Stop the credential-broker before replacing its database. Take a SQLite online
backup before an upgrade or migration:

```bash
python -m cloudbrowser.credential_broker.grant_admin backup \
  --db /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/backups/grant-custody-v1.before.sqlite3
```

Rollback requires a v1 custody backup. It first saves the current database as
`--current-backup`, validates the backup schema, then atomically replaces the
live database. It never merges rows, so rollback restores all principals and
cannot cross-copy a grant between users:

```bash
python -m cloudbrowser.credential_broker.grant_admin rollback \
  --db /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/backups/grant-custody-v1.before.sqlite3 \
  --current-backup /data/state/backups/grant-custody-v1.failed.sqlite3
```

After rollback, restart the broker and check each affected immutable binding
with `status`. Keep both backup artifacts under owner-only permissions and
retain the operator/audit record. Never delete the legacy backup until explicit
reprovisioning and verification are complete.


The offline CLI is `python -m cloudbrowser.credential_broker.grant_admin`.
Run it only from an owner-controlled host or secret-management wrapper. Do not
put the KEK, vault key, refresh token, or a master password in shell history.
The JSON document is read from stdin and is not written back:

```bash
umask 077
export GRANT_KEK_HEX='hex:<64 hex characters from the operator secret source>'
python -m cloudbrowser.credential_broker.grant_admin provision \
  --db /data/state/grant-custody-v1.sqlite3 \
  --kek-hex "$GRANT_KEK_HEX" \
  --profile-id '<immutable profile id>' \
  --principal-id '<immutable principal id>' \
  --site-id '<declared site id>' \
  --target-tab-id '<exact target tab id>' \
  --browser-id '<immutable browser id>' \
  --generation '<current binding generation>' \
  --operator-id '<audited operator id>' <<'JSON'
{"item_ref":"<exact Vaultwarden item id or reviewed reference>","vault_key_hex":"<128 hex characters>","refresh_token":"<captured refresh token>"}
JSON
unset GRANT_KEK_HEX
```

The command prints only `{status, grant_ref, epoch}`. The `grant_ref` is opaque
and is not sufficient to select another principal. The broker database must be
mounted only into the credential-broker service; it is not mounted into the
router, browser, slot, viewer, or agent-control services.

Check status without material:

```bash
python -m cloudbrowser.credential_broker.grant_admin status \
  --db /data/state/grant-custody-v1.sqlite3 --kek-hex "$GRANT_KEK_HEX" \
  --profile-id '<profile>' --principal-id '<principal>' --site-id '<site>' \
  --target-tab-id '<tab>' --browser-id '<browser>' --generation '<generation>' \
  --operator-id '<operator>'
```

Expected usable state is `active: true`, `has_vault_key: true`,
`has_session_leg: true`, `usable: true`. Status and audit output are
status-only. A key-only or session-only row is never usable.

Revoke on user consent withdrawal, browser reassignment, incident response, or
operator offboarding:

```bash
python -m cloudbrowser.credential_broker.grant_admin revoke \
  --db /data/state/grant-custody-v1.sqlite3 --kek-hex "$GRANT_KEK_HEX" \
  --profile-id '<profile>' --principal-id '<principal>' --site-id '<site>' \
  --target-tab-id '<tab>' --browser-id '<browser>' --generation '<generation>' \
  --operator-id '<operator>'
```

Revoke returns only `status` and the new epoch. Any in-flight call that has not
passed its next epoch recheck fails closed; already minted Vaultwarden access
may remain valid only for Vaultwarden's short configured lifetime.

## Broker runtime integration

The completed custody implementation is deliberately not auto-wired from
`CB_VAULT_EMAIL`/`CB_VAULT_PASSWORD`: those deployment-wide credentials violate
G5 and would make a fresh install appear usable when no per-user grant exists.
At source checkpoint `430a066`, `build_broker_api` already wires
`ProductionGrantResolver` (a `CustodyGrantStore` subclass) and
`CustodyCredentialFetcher` when no test fetcher is injected. Startup requires
`CB_BROKER_GRANT_KEK_HEX` and `CB_VAULT_BASE_URL`; a usable grant must match
the browser/router binding tuple. Missing authorization must yield
`not_shared`/dependency failure, never a shared vault account fallback.

This source wiring is distinct from provisioning and live qualification. The
current full-tuple key also leaves consent reuse after tab/generation changes
unproven. The proposed [roadmap](ROADMAP.md) schedules a grant-lifetime decision
and recovery acceptance without weakening request-level binding or revocation.

This milestone does not claim live GrantHub capture, live Vaultwarden access,
or deployment. The fake-vault contract tests prove provision → opaque resolve →
refresh mint/sync/decrypt → refresh rotation → revoke/no-new-read and scan
SQLite/audit output for secret absence.
