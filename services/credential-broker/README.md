# Credential Broker service

The Credential Broker owns deterministic, status-only login execution. Its
production credential source is a per-user, principal-scoped GrantHub grant;
it is not a deployment-wide Vaultwarden account. Grant provisioning/revocation
is operator-controlled and offline; no network admin endpoint is exposed.

## Versioned grant custody state

The broker uses the owner-only `/data/state/grant-custody-v1.sqlite3` database.
The file has explicit schema metadata (`cloudbrowser.grant-custody.v1`, version
`1`); startup refuses the old `grants.sqlite3` path/table, missing metadata,
and unsupported versions instead of silently creating or ignoring state.

For an existing installation, migrate offline with the grant admin CLI:

```bash
python -m cloudbrowser.credential_broker.grant_admin migrate-legacy \
  --source /data/state/grants.sqlite3 \
  --destination /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/grants.legacy.backup.sqlite3 \
  --kek-hex "$GRANT_KEK_HEX" --operator-id '<operator>'
```

This is intentionally backup-only: old rows lack the two custody legs and are
never inferred into active per-user grants. The command returns
`reprovision_required` with `migrated: 0`; explicitly reprovision each immutable
profile/principal/site/target/browser/generation binding.

Before a state change, stop the broker and back up the custody DB. Rollback
validates the v1 backup, saves the current DB, and atomically replaces it; it
never merges rows or copies one principal's grant to another:

```bash
python -m cloudbrowser.credential_broker.grant_admin backup \
  --db /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/backups/grant-custody-v1.before.sqlite3
python -m cloudbrowser.credential_broker.grant_admin rollback \
  --db /data/state/grant-custody-v1.sqlite3 \
  --backup /data/state/backups/grant-custody-v1.before.sqlite3 \
  --current-backup /data/state/backups/grant-custody-v1.failed.sqlite3
```


This source tree contains the secure broker boundary and capability plumbing;
it is not a claim that every final-product login path is shipped or qualified.
The current runtime posture is:

- **Form login:** unavailable in production. `CB_BROKER_ADAPTER=form` exits at
  startup until a broker-only, exact-target form capability is qualified.
  The prior form proof is historical test evidence only; the corresponding
  Layer 4 integration tests are intentionally skipped.
- **HTTP request boundary:** the public login route accepts only an opaque,
  signed, one-time capability. The caller cannot submit a username reference,
  password, token, alternate principal, or global grant selector; the broker
  derives the principal-scoped grant from the verified capability and live
  binding.
- **Durable state:** grant authorization, idempotency, and nonce records are
  persisted under the broker state volume and are scoped to the principal,
  site, target, request, and generation as applicable. A caller-selected global
  grant reference is forbidden.
- **Grant custody:** the production GrantHub path stores wrapped two-leg grant
  material and bounded metadata in the versioned
  `/data/state/grant-custody-v1.sqlite3` database. Startup rejects the legacy
  `grants.sqlite3` path/table and unknown custody schema versions; plaintext is
  held only during one broker call. Provisioning requires the approved operator
  flow and never asks the agent for a master password or exposes a vault
  key/session leg.
- **Authentik SSO:** the runtime can enter the declared Authentik flow and
  detect an MFA stage, but it does not submit TOTP and does not perform a human
  one-time-code handoff. Application identity proof and live closed-shadow
  qualification are not qualified.
- **Release state:** source/test work is not the same as a published,
  digest-synced, live-qualified release. The image pins currently in the shared
  release files are stale relative to this work and are intentionally left
  unchanged in this milestone.

## What is implemented in the current source slice

- server-derived profile/principal/browser binding and status-only results;
- a second binding and grant check after fetch and immediately before adapter
  execution;
- principal-scoped durable grant lookup, idempotency, and one-time nonce state;
- per-call broker-only grant consumption; no retained access/refresh token in
  the normal agent or browser surfaces;
- a secret-gated broker-only Basic browser capability using CDP
  `Fetch.authRequired` / `Fetch.continueWithAuth` (not exposed through the
  router/agent-control allowlist);
- `cloudbrowser.audit.v1` metadata events with credential-shaped payload
  rejection.
- The current local source slice includes the exact-origin HTTP Basic adapter;
  its published/live qualification remains a separate release gate.

These are implementation claims, not live qualification claims. The final
product requirements remain in
[`specs/proposals/v0.2/85-credential-broker-prd.md`](../../specs/proposals/v0.2/85-credential-broker-prd.md):
ordinary form login, TOTP submission, human one-time-code handoff, SSO
application proof, and recovery qualification still have to be demonstrated
before the Credential Broker product can be marked complete.

## Operator flow and release sequence

1. Obtain the current owner binding from the authenticated control plane:
   `profile_id`, immutable `principal_id`, `browser_id`, current `generation`,
   exact `site_id`, and exact `target_tab_id`.
2. Provision/revoke the matching GrantHub custody record through the approved
   offline operator CLI, supplying sensitive JSON only through stdin. Confirm
   outputs contain status/opaque references/epoch metadata only. For an existing
   install, run `migrate-legacy` first; legacy rows are backed up but never
   inferred into active custody grants.
3. Before a state upgrade, run the CLI `backup` command. If rollback is needed,
   stop the broker and use `rollback`, which saves the current v1 database and
   atomically restores the validated backup without merging users.
4. Commit the source and spec/test changes together. Run the local validators
   and record the source commit.
5. An authorized operator or agent triggers the GitHub Actions build from the
   reviewed source commit. Follow the validation and qualification gates in
   the current roadmap; an earlier task's token budget is not a release rule.
6. After the build and provenance/SBOM checks pass, resolve the immutable
   service digests and synchronize the compose/release-manifest/
   image-qualification records in a separate release step.
7. Run the provenance and full gates against the synchronized pins; only then
   request live deployment or closed-shadow qualification.

Do not edit stale release digest pins as part of this source/spec checkpoint.
A green local test run does not establish image provenance, live deployment, or
Authentik qualification.

## Product continuity

The current custody key includes the exact tab and browser generation. Safe
reuse of user consent after those values change still requires a demonstrated
reauthorization flow. Offline provisioning is an operator capability; employee
self-service consent and complete restart/recovery acceptance remain roadmap
work. See [implementation status](../../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md)
and the proposed [roadmap](../../specs/proposals/v0.2/ROADMAP.md).
