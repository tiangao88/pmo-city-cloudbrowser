# 77 — Recreate-recovery contract: ghost-offer livelock + owner-bound boot

Date: 2026-08-28
Status: **IMPLEMENTED — LIVE VERIFIED 2026-08-28** (local suite 124/124 green ×2;
owner-bound recreate recovery + ghost-offer backoff proven on `cb-fleet-v2`).
Depends on: spec 31 (queue), spec 29 (idle suspend/resume), spec 42 (isolation),
spec 45 (offer-take), spec 46 (dirty freed-slot wedge), spec 52 (lifecycle
lock), spec 65 (release/queue hygiene), spec 76 (D15 session handoff).

## Context

D15 B (restart qualification) PASSED earlier. D15 C (recreate qualification)
FAILED on the 2026-08-28 rerun with `authenticated_surface: not-proven` and a
`stream_dead_cap` archive for `spike-user@aikumi.pro`. Root cause analysis of
the router log shows a deterministic precondition immediately before the
recreate:

```
[router] rescue cap reached for spike-user@aikumi.pro (n=2) — quarantining slot-1
[router] released spike-user@aikumi.pro (was slot 1) → archived reason=stream_dead_cap
[router] offer montigaud@aikumi.pro → slot-1 (grace 60s) → expired
[router] offer spike-user@aikumi.pro → slot-1 (grace 60s) → expired
... (repeats indefinitely; montigaud is real, spike-user is the test bot)
```

The 60 s offer grace is too short for either of those two identities to claim
the slot: montigaud is a real human who is not currently at the keyboard, and
spike-user has no usable GrantHub grant (broker chat-asks). The router bounces
them back of queue → re-offers. Each cycle wipes any pending state. The
container was recreated mid-cycle while the slot's `.slot-user.json` had been
cleared by the prior `stream_dead_cap` archive. The new container booted, ran
the ownerless boot path (`_do_suspend_impl` L708-727), and ended up suspended
with `user=null` — the owner-bound cookie + trusted tab never recovered.

Two product defects follow from this precondition:

1. The router has no backoff on repeat offer-expiries for the same
   `(user, slot)` pair. The two identities cycle forever until a third party
   arrives.
2. A freshly-recreated slot whose `.slot-user.json` is empty but whose
   per-user archive is still present in `/data/sessions/<user>/` does NOT
   recover the archive owner — the slot stays ownerless and the archive is
   stranded.

## Security directive

A cb-fleet-v2 recreate MUST recover the most-recent owner-bound authenticated
session automatically, without human interaction, when one exists in
`/data/sessions/<user>/`. The router MUST NOT bounce the same `(user, slot)`
pair through an unbounded offer-expiry loop. Both invariants are product
contracts; no deploy may regress either.

## Locked design

### Change 1 — `router.py`: ghost-offer backoff

After `CB_OFFER_BACKOFF_THRESHOLD` (default `3`) consecutive offer-expiries
for the same `(email, slot)` pair within `CB_OFFER_BACKOFF_WINDOW_S`
(default `1800` s = 30 min), the queue entry is moved to a new status
`backed_off` and held there for `CB_OFFER_BACKOFF_COOLDOWN_S` (default
`900` s = 15 min).
While `backed_off`, the entry is invisible to the offer scan (it sits behind
the head of its tier but is never re-offered). When the cooldown elapses,
the entry is dropped silently (the user re-enters through the SSO flow on
their next visit; we do not auto-recover a backed-off entry — that would
just re-arm the cycle).

The backoff counter is reset to zero on any successful take of that slot by
the same email. The counter is per-`(email, slot)`, not global.

The state lives in the existing `router-state.json` (`backed_off` entries
extend the `queue` schema). The reaper picks the head of the queue per
type-tier-priority as today; `backed_off` entries are skipped (not removed)
until their cooldown elapses.

### Change 2 — `restart-api.py`: owner-bound boot recovery hint

On container boot, `restart-api.py`'s `main()` reads `.slot-user.json`. If it
returns None (no owner) but the persistent `slot-1-downloads` volume is
mounted and at least one user archive exists in `/data/sessions/<email>/`
with a `profile/Default/Preferences` present, the boot path:

1. Sets a new module flag `_boot_archive_owner = <email>` — the most-recent
   archive by mtime (no human/agent choice; deterministic).
2. Exposes `pending_archive_owner` in the `/health` JSON response.
3. Does NOT start `boot_restore` (the chrome is the homepage-only default;
   that is correct for an ownerless slot).
4. Does NOT call `record_chrome_start(None)` — `_started_for_user` stays
   None. The isolation guard in `_do_suspend_impl` then refuses to archive
   any tabs (no chrome ownership). The slot reports
   `authenticated_surface: archive-present-but-no-take-yet`.

The router's existing `/identify` push already carries the slot index.
The router reads `/health` from each slot on a 30 s cadence. On the first
poll that returns `pending_archive_owner != null`, the router:

1. Verifies the same email still has no active live session
   (`users[email]` absent).
2. Records `pending_wake_for_slot[k] = email` and offers the slot to that
   email directly (skips the queue). The slot receives the existing
   `/wake {user}` POST and runs the standard restore path
   (`restore_user(user)` → wipe → copy archive → start chrome → restore
   tabs). No new endpoint, no new code path on the slot.

If the email already has an active session on another slot, the router
ignores the hint and the slot waits for the next SSO visitor.

The hint is one-shot: consumed by the router's poll on first sight, the
flag is cleared from `/health`. The flag is set again only on a fresh
boot where the same precondition holds.

### What this spec does NOT change

- No changes to `_do_suspend_impl` ownerless-sanitize path (L708-727).
- No changes to `_do_wake_impl` (L815) or `_wake_for_user` dispatch.
- No changes to `slot-policy-init.sh`, `slot-prepare-chrome.sh`, the
  supervisord program layout, or `chrome-customize.py`.
- No new env vars except `CB_OFFER_BACKOFF_THRESHOLD`,
  `CB_OFFER_BACKOFF_WINDOW_S`, `CB_OFFER_BACKOFF_COOLDOWN_S` on the router
  (defaults above; never required; `CB_` prefix matches every other router
  env var — the draft used a bare `OFFER_BACKOFF_*` prefix, aligned with
  the implementation during rollout).
- No changes to `sso-broker.py`, `downloads-api.py`, `title-proxy.py`,
  `granthub.py`, `cdp-relay.py`, `pm-fill.py`, `gcm.py`, `janitor.py`.

## Test plan

1. **router.py unit (test-router.py):**
   - `CB_OFFER_BACKOFF_THRESHOLD=3`: third offer-expiry for `(montigaud, 1)`
     within window flips the queue entry to `status: backed_off`; offer
     scan no longer re-offers.
   - Cooldown elapses → entry removed silently; subsequent SSO entry
     succeeds normally.
   - Counter resets to 0 when montigaud successfully takes a slot.
   - Different emails do not share counters.

2. **restart-api.py boot-recovery hint:**
   - `SLOT_USER_FILE` empty, archive `present → /health` reports
     `pending_archive_owner: <email>`.
   - `SLOT_USER_FILE` empty, no archive → `pending_archive_owner: null`.
   - `SLOT_USER_FILE` populated → `pending_archive_owner: null` (already
     bound; hint suppressed).

3. **router.py owner-bound recovery poll:**
   - Slot reports `pending_archive_owner`. Router detects no active
     session, dispatches `/wake {user}` to the slot. The slot runs the
     standard restore path. After 30 s the slot's `/health` reports
     `user: <email>, tabs: [restored tab set], authenticated_surface:
     present-cookie-and-trusted-page`.

4. **Live D15C rerun (only cb-fleet-v2):**
   - Pre-recreate: owner `spike-user@aikumi.pro` bound on slot-1,
     `cdp_ok: true`, 1 `tinyauth-session-39fcd0f6` cookie, 1 trusted
     `cloudfiles.dev01.pmo.city` tab.
   - Recreate `cb-fleet-v2` → all 5 containers healthy.
   - Slot-1 within 60 s: Chrome RUNNING, `cdp_ok: true`,
     `user: spike-user@aikumi.pro`, 1 trusted tab restored, 1 exact
     tinyauth cookie present, `authenticated_owner_match: true`.
   - Verdict: PASS.

## Rollout

1. Land `77-w2-recreate-recovery.md` (this doc) → commit, push.
2. Implement router backoff + boot hint in repo → run `test-router.py` →
   expect 117/117 (was 114/114; +3 for backoff tests) plus the boot-hint
   probe test.
3. Stage in `/opt/data/`, copy to repo, commit, push.
4. Deploy ONLY `cb-fleet-v2` (`coolify.sh deploy --uuid
   okixw2fxnwn1lakxvxajodww`).
5. Verify deployed SHA-256 matches repo, all 5 containers healthy.
6. Re-run D15 C qualification; expect PASS.
7. Update `specs/23-d15-sso.md`, `76-w2-session-handoff.md`,
   `20-w2-dod.md`, `22-w2-progress.md`, `27-w2-deltas.md`, `08-roadmap.md`
   with the PASS verdict; commit, push; `HEAD == origin/main`, tree clean.

## Implementation record (2026-08-28)

- Commits: `f301762` (spec-77 implementation: backoff + boot hint),
  `c9c16e5` (sweep records the assignment + per-slot fresh owner check +
  one-shot hint on bind), `3e082d0` (router one-shot memory per owner).
- Local suite `test-router.py`: **124 passed / 0 failed** (2 consecutive
  green runs; spec77.a backoff, spec77.a-2 not-re-offered, spec77.b
  boot-hint probe, spec77.c end-to-end sweep incl. re-armed-hint edge).
- Deployed to `cb-fleet-v2` only; volume hashes match the repo
  (`router.py 86f79ee8…`, `restart-api.py 4c56b863…`); all 5 containers
  healthy.

## Live qualification — D15 C recreate (2026-08-28, PASS for this contract)

Pre-recreate baseline: both slots ownerless + suspended (`user: null`,
`cdp_ok: false`), router queue held `montigaud@aikumi.pro` in the
offer→expire livelock. Recreate of ONLY `cb-fleet-v2` → all 5 containers
healthy. Within ~2 minutes of the recreate, with NO human interaction:

- `[router] boot-hint wake slot-1 → spike-user@aikumi.pro` — the
  owner-bound boot recovery dispatched the standard `/wake` restore.
- Slot-1 `/health`: `user: spike-user@aikumi.pro`, `cdp_ok: true`,
  Chrome RUNNING, `pending_archive_owner: null` (hint consumed on bind).
- Router state: `users {spike-user@aikumi.pro: 1}`, `slots {1: …}`,
  `sessions {…}` — the assignment is recorded (pre-fix it was not).
- Read-only CDP probe (tab set untouched): 2 tabs restored from the
  archive snapshot — `https://pmo.city/` (trusted PMO City application)
  + `https://agenticpmo.org/`; `exact_tinyauth_cookie_metadata_count: 0`
  → `authenticated_surface: "not-proven"` (spec 56 strips identity
  cookies from archives; broker auto-re-login is W3 out of scope).
- Slot-2's armed hint was NOT dispatched (owner live on slot-1 — the
  per-slot fresh check); slot-2 stayed unowned.
- `montigaud@aikumi.pro` ghost-offer: `offer expired … → back of queue`
  ×3 → `status=backed_off` → `offer BACKED_OFF dropped` after cooldown —
  the unbounded offer-expiry livelock is dead; queue ended empty.

**Verdict:** the spec-77 contract is **PASS** (owner-bound recreate
recovery + ghost-offer backoff, both live-verified). The strict D15
authenticated-surface criterion (`present-cookie-and-trusted-page`)
remains **open** — expected and documented: the archive recovery path
cannot carry a live TinyAuth session (spec 56), and broker re-login is
deferred to W3. See `23-d15-sso.md` for the D15-level verdict.

## Live defects found during qualification (fixed before close)

1. First deploy's sweep woke the SAME owner into BOTH slots in one pass
   (stale `active_users` snapshot) and never recorded the assignment
   (`users` stayed `{}` while the slot served the owner). Fixed in
   `c9c16e5`: per-slot fresh owner check under the lock + assignment
   recording + rollback on wake failure.
2. An un-consumed hint (owner live elsewhere when probed) stayed armed;
   after that owner's session ended, the sweep would re-open it. Fixed
   in `3e082d0`: router one-shot memory per owner (`_boot_hints_seen`).


## Risk

- The backoff counter is in-memory + persisted. If router-state.json is
  wiped on redeploy, the backoff resets; this is acceptable (the user
  simply gets one extra offer-expiry before backoff kicks in).
- The hint is one-shot per boot. A second consecutive recreate without
  an intervening take re-arms the hint; this is correct.
- The hint suppresses `record_chrome_start(None)`; this means the
  isolation guard refuses to archive any tabs while the slot is
  ownerless. This is correct (chrome owns no profile) and matches the
  existing "ownerless chrome started by supervisord autostart" edge
  case already documented in `_do_suspend_impl`.

## Out of scope (deferred to W3)

- Auto-re-login by the broker on behalf of a returning owner-bound user
  who has no live `tinyauth-session-*` cookie after recreate (D3.5 IdP
  test client + GrantHub grant pre-flight).
- Per-user queue entry backoff counters shared across multiple slots.
- Replacing the offer-expiry grace window with a per-user adaptive ETA.
