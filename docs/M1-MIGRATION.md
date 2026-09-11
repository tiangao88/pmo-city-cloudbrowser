# M1 rollout and recovery checklist

Source preparation only, 2026-09-11. No live migration, image publication or
deployment has been performed. See [ADR-0005](../specs/adr/0005-m1-personal-state-and-consent.md).

## Before any rollout

1. Obtain environment-specific deployment and data-migration approval. Complete
   the outstanding independent broker review and current-source image gates.
2. Identify stable principal/profile mappings from trusted identity records.
   Never infer an owner from a directory name, cookie, account email or last
   slot occupant. Inventory profile/download paths and grant modes without
   printing personal browser data or custody material.
3. Drain the affected slots and stop browser processes. Back up the profile,
   browser-download and supervisor-state volumes plus the custody database
   using its offline `backup` operation. Keep encryption/key dependencies in
   approved secret storage, not in Git or an ordinary evidence attachment.
   Record the prior images/configuration and verify a disposable restore.
4. All slots of this installation must share the same profile root and
   browser-download root with compatible service ownership and local filesystem
   advisory locking. Do not share these roots across installations or use NFS.
   Browser and supervisor images must be upgraded together: native tab restore
   replaces the production supervisor's snapshot replay.

## Profile and download compatibility

New profiles are selected under `owners-v1/<stable-owner-key>`. Existing root-level
`Default` data and pending root-level downloads are left intact but unused.
An empty new owner profile is the safe default, not a silent migration failure.
Do not copy an ambiguous old profile into every user's directory. If an old
profile has one independently verified owner, plan and authorize its offline
migration separately, preserving the approved backup and validating cookies,
storage, tabs and download attribution before allowing another user in.

Normal stop uses private lifecycle-only `Browser.close` and waits for process
exit, allowing Chromium to save its state. A forced stop/crash can leave
`SingletonLock`. Automatic recovery then fails closed. Before any manual lock
cleanup, drain every slot sharing that root and establish that no Chromium
process anywhere in those containers owns the profile. An uncertain marker is
not permission to delete it. Preserve a backup and validate recovery with the
same owner before reopening access. This milestone does not provide automated
crash reconciliation or a multi-host distributed lock.

## Grant compatibility

Existing exact grants retain their tab/browser/generation scope. To opt a user
into consent-until-revoked for a declared site:

1. Back up custody and obtain explicit approval for the stable owner/profile,
   site and selected account. Employee self-service approval is future M3 work.
2. Revoke every active exact grant for that owner/profile/site using its existing
   exact binding. New consent provisioning refuses an active mixed mode.
3. Use `provision-consent` with database, KEK, profile, principal, site and
   operator arguments. Supply the two custody legs and item reference through
   the existing protected stdin document, never ordinary command arguments,
   chat, shell history or logs. Use an approved local secret wrapper for the KEK.
4. Verify `status-consent`, a fresh tab/generation request, and `revoke-consent`
   against approved qualification data before accepting the live journey.

Revocation blocks subsequent broker credential use; it does not invalidate an
existing application login. Application logout/session invalidation is separate.
There is one selected account per owner/profile/site, no automatic account merge.

## Rollback

Keep access drained during rollback. The prior runtime cannot use new consent
rows for real tabs, but it also does not implement the new owner-directory
contract. A simple image downgrade is therefore **not a qualified multi-user
rollback**. Restore the approved image/configuration and matching validated
state backup under an explicit recovery plan; verify ownership before reopening
access. Do not restore revoked authorization from an old backup without current
approval, or merge personal profiles/grants to recover availability.
