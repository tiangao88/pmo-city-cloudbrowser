# ADR-0005: Persistent owner storage and explicit durable consent

Status: implementation decision for authorized M1 development, 2026-09-11.
No live deployment or live-data migration is authorized by this document.

## Personal browser state

`CB_PROFILE_DIR` becomes a storage root. Production profiles use
`owners-v1/SHA256([principal_id, profile_id])` below that root. Slot/browser ID,
tab ID, and generation never select persistent data. Chromium restores its own
last session; operational request bindings remain generation-specific.

Acquire an exclusive advisory filesystem lease before modifying a profile or
starting Chromium. Hold it until the process stops; a second slot using the same
shared volume fails closed. All slots in one installation must mount the same
profile root for cross-slot continuity; separate installations must not share it.
This single-host design relies on filesystem flock semantics, not NFS locking.

Reject owner-path symlinks. Existing unpartitioned profile data stays in place
and is never automatically attributed to a user. Prior ambiguous data requires
an offline ownership review and backup before a separately approved migration.
Identity cookies are stripped before Chrome starts, preserving the existing
spec-56 policy. Ordinary application state remains per owner.

Downloads use the same stable key under the separate browser-download root.
Rotate path and attribution together under the watcher's scan lock; a leftover
file can only be retried when its owner returns. Chromium preferences select
the matching owner directory. This does not change durable CloudFiles identity.

## Durable consent versus one-request authorization

Keep existing exact-scope grants unchanged. Add explicit offline
`provision-consent`, `status-consent`, and `revoke-consent` operations keyed by
profile, principal and declared site. Consent is one selected account per site;
multiple-account selection remains outside this increment.

Use the existing v1 authenticated ciphertext format with the versioned reserved
tuple `@consent:v1` for the stored tab/browser/generation fields. The reserved
tuple is an explicit consent record, never an actual browser binding. Partial
reserved tuples are rejected. An older runtime cannot resolve such a row for a
real tab, so rollback fails closed rather than granting broader access.

No schema rewrite or automatic consent widening occurs. To change from exact
grants to consent, revoke the old active records and explicitly reprovision the
two custody legs in consent mode. Active exact and consent grants cannot coexist
for the same owner/profile/site. Take a custody backup first; no live migration
is performed by M1 source work.

Resolution still derives the current browser, generation and exact tab from the
authenticated router/broker flow. Its returned authorization contains those
fresh values, while custody stays stable. The signed capability, nonce,
idempotency, origin/account verification and pre/post live-binding checks remain
mandatory. A durable consent row is never an agent capability or a reason to
accept a stale browser request. Revocation/refresh rotation use the same row,
epoch and transactional lock across all generations.

## Acceptance

Test A → B → A state and tab recovery, two-slot exclusion, restart on a second
slot, symlink rejection, owner-correct leftover downloads, old exact-grant
behavior, explicit consent provisioning, new-tab/generation reuse, revocation,
cross-owner/profile/site rejection and authorized execution under the existing
broker boundary. Real-browser tests use only disposable profiles and local
synthetic application state; no user sign-in is required for this increment.
