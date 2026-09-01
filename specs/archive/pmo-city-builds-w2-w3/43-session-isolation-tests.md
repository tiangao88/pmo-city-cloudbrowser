# Spec 43 — Session Isolation Tests: Prove the Leak Is Dead

> **Status: LOCKED (Tigo, 2026-08-22).** Verifies spec 42. Green = incident
> closed. Run order: T1–T5 (scripted, before deploy) → deploy → T6–T10
> (live, after deploy).

## 0. Test philosophy

Every test must be able to **fail loudly**: a tab from user A appearing in
user B's session/archive is a FAIL (not a warning). The suite targets the
exact storm conditions from the incident (spec 41 §3), then the normal paths.

## 1. Scripted tests (host-side, against code, before deploy)

### T1 — do_wake: same-user re-offer is a no-op
- Setup: `slot_user() == "alice"`, chrome RUNNING.
- Call `do_wake("alice")`.
- **PASS:** no wipe, no restore copy (mtime of profile dir unchanged), chrome
  still RUNNING, return `{"ok": True, "note": "already up"}`.

### T2 — do_wake: user switch stops chrome BEFORE restore
- Setup: `slot_user() == "alice"`, chrome RUNNING (pid X).
- Call `do_wake("bob")`.
- **PASS:** chrome STOPPED before `restore_user` (log order:
  `wake user-switch alice -> bob` → `restored bob` → `chrome started`);
  chrome pid after = new pid (≠ X); `slot_user() == "bob"`.

### T3 — do_suspend: pid mismatch → snapshot skipped, stale cleared
- Setup: `_started_pid = 111`, running chrome pid = 222 (simulate foreign).
- Call `do_suspend("alice")`.
- **PASS:** log contains `isolation guard`; `SNAPSHOT_FILE` absent after;
  archive `profile/tab-snapshot.json` absent/not written.

### T4 — restore_user: archive marker mismatch → refuse
- Setup: archive dir `bob` containing `.archive-user.json` with `user: alice`.
- Call `restore_user("bob")`.
- **PASS:** returns False, ERROR logged, profile not copied.

### T5 — archive marker written
- Call `archive_user("alice")`.
- **PASS:** archive root contains `.archive-user.json` with
  `{"user": "alice", ...}`.

## 2. Live tests (after deploy, on the real fleet)

> Fleet = 1 human slot (slot-1) + router. Uses existing test users
> (spike-user, spike-user2, montigaud) — all Tigo-controlled.

### T6 — storm regression: offer cycle must NOT touch the slot
- Seed queue with two users (spike-user, spike-user2) and NO one taking.
- Wait ≥ 2 offer cycles (≥ 120 s).
- **PASS:** router log shows NO `POST /wake` during the window; slot log
  shows no `restored X` / no `chrome started`; slot stays suspended
  (`chrome: STOPPED`).

### T7 — user-switch isolation (the incident replay)
1. User A (spike-user) takes slot; open a **marker tab** `https://pmo.city/marker-A`.
2. Release (tab-bar Exit / idle) → archived.
3. User B (montigaud) takes slot.
4. **PASS:** B's session shows **no marker-A tab**; B's History has no
   marker-A visit; B's archive snapshot after suspend has no marker-A.
5. Reverse (B→A): same, marker-B must not appear in A.

### T8 — same-user resume still works (regression)
- User A takes slot again after T7.
- **PASS:** A's tabs from A's archive restored (snapshot honored); chrome
  restarted (new pid); session works.

### T9 — no-archive fresh wake (regression, spec 31)
- A user with no archive takes the slot (e.g. `tigo-test@x.pro` or a new
  test user).
- **PASS:** fresh wake (wipe, empty profile, chrome starts), no 500.

### T10 — archive integrity sweep (post-tests)
- For every archive: `.archive-user.json` present; `tab-snapshot.json` URLs
  checked against the archive owner's known session; no foreign `History`
  rows (spot-check).
- **PASS:** all archives consistent; contamination (incident §5) purged.

## 3. Result log

## Reconciliation record (2026-08-31)

The roadmap's former wording treated T6/T8/T9 and the full T7 replay as
pending. That was stale: the result log below records live green T6–T10
against the deployed isolation fix. The roadmap now identifies T6–T10 as
complete. This does **not** close W3-1A's separate two-browser identity
observation, which remains pending in `81-w3-1a-identity-queue-reconciliation.md`.

> Executed 2026-08-22 (UTC) against `6e6fb7e` (scripted) + **live 23:2x–23:45
> UTC against `596bb72`** (T6–T10, real fleet slot-1/router). Scripted suite =
> sandbox harness (`scripts/test_isolation.py`, mocked supervisorctl + /proc);
> live suite = real fleet (slot-1, router). See spec 42 §7 for the
> deployed fix set.

| Test | Result | Evidence (log line / file) |
|---|---|---|
| T1 same-user no-op | ✅ GREEN | scripted: `wake same-user alice@x.pro — already up (no-op)`, no supervisor calls; live not exercised (see T8 note) |
| T2 user-switch stop | ✅ GREEN | scripted + LIVE: `wake user-switch montigaud -> spike-user — stopping chrome` then `restored …` then `chrome started` (stop precedes restore) |
| T3 suspend pid guard | ✅ GREEN | scripted: `SUSPEND isolation guard — chrome does not own the profile; snapshot skipped, stale snapshot cleared`; live: guard silent (chrome owned profile — correct) |
| T4 marker mismatch | ✅ GREEN | scripted: `restore REFUSED — archive bob@x.pro is owned by alice@x.pro (contamination); fresh wake` |
| T5 marker written | ✅ GREEN | scripted: marker present after `archive_user`; live: all 3 archives carry `.archive-user.json` |
| T6 storm regression | ✅ GREEN | **LIVE 2026-08-22 23:3x UTC** (router `596bb72`): free slot + 2–3 user queue seeded (spike-user, spike-user2, + montigaud re-entry from his live tab), nobody takes. Slot-1 `/health` polled 16/16 over 4 min: `suspended=True chrome=STOPPED cdp_ok=False` — **never touched**. Router log: `offer`/`offer expired` cycles only, **zero** wake/take/suspend lines. Offer-time pre-wake removal (spec 42) + reaper self-heal (spec 46) both held |
| T7 isolation replay | ✅ GREEN | **LIVE**: A=spike-user takes (take woke the slot — spec 46), opens marker tab `https://pmo.city/marker-A` via CDP. Release → B=spike-user2 takes. B's tabs: `['chrome://newtab/']` — **no marker-A**; B's archive History: marker-B only (his own), **no marker-A**. Reverse: B opens `marker-B`, releases; A re-takes → tabs `['marker-A','newtab']` — **no marker-B**; A's History: marker-A only. Each user's History/snapshot holds ONLY their own marker |
| T8 same-user resume | ✅ GREEN | **LIVE**: A re-take → restart-api `watchdog: chrome pid changed … queueing restore` → `tab-restore: opened 2 tab(s) from snapshot` → tabs `[https://pmo.city/marker-A, https://pmo.city/t8-check]` restored (snapshot captured by pre-suspend `do_suspend`). Same-user archive restore honored |
| T9 fresh wake | ✅ GREEN | **LIVE**: tigo-test@x.pro (archive purged pre-test) takes → `tab-restore: no snapshot — nothing to restore` → `zero tabs -> opened homepage https://pmo.city`; `chrome RUNNING cdp_ok=True user=tigo-test`; **no 500/traceback**. Fresh profile, no restore |
| T10 archive sweep | ✅ GREEN | **LIVE**: 6/6 archives carry `.archive-user.json` with owner==dir-name (2 legacy pre-spec-42 archives `a2`, `expiry-a` marked retroactively). No marker-A/B cross-contamination anywhere (snapshot + History checked per archive) |

**Live test notes (2026-08-22, 23:2x–23:45 UTC, router `596bb72`):**
- Test drives used the router's Remote-Email header via `docker exec` (same path the
  tinyauth gateway uses) + CDP relay (host `:9223`) for marker tabs / tab+History
  verification. marker URLs `https://pmo.city/marker-{A,B}` are 404s — chosen as
  unambiguous per-user tokens, never a real page.
- Pre-test maintenance window (Tigo-approved): suspended slot-1, dropped montigaud's
  stale queue entry via `POST /fleet/release` (archive preserved), purged the
  tigo-test archive. montigaud's live tab re-entered the queue once — harmless storm
  noise (waiting only, no take possible without a click).
- **Snapshot-watchdog observation (follow-up):** `tab-snapshot.json` was NOT written
  by the watchdog during remote-driven sessions (the W3 snapshot path is gated on
  `chrome_owns_profile()` pid-match; `do_suspend`'s pre-suspend snapshot covered the
  release). Tab persistence for these sessions came from the per-user profile archive
  (Chrome session files) + the pre-suspend snapshot — isolation unaffected, but the
  watchdog-snapshot gating is worth a look (W3/deltas).

**Live deployment notes (2026-08-22):**
- Deployed 20:29 UTC: `docker restart slot-1 router` (scripts volume mounted);
  both `healthy`. Slot boot: `boot restore (browser at empty state)` →
  `opened 1 tab(s) from snapshot` (auth flow only — PMBOK gone).
- Suspend → wake spike-user → wake montigaud sequence ran live; every
  transition logged `wake user-switch … — stopping chrome` (isolation
  invariant). `/idle` returned `user: montigaud@aikumi.pro, status: active`.
- Post-fix, montigaud's own browser opened PMBOK again (20:25–20:31,
  re-archived at 20:31 with his snapshot) — **his own navigation**, no
  restore/wake in that window; not a leak. Live profile = `google-chrome`
  (env `PROFILE_DIR`), confirmed via snapshot + Cookies.
- Incident data purge (spec 42 §5) ran against the sessions volume before
  deploy; archives are clean + marked.

## 4. Sign-off

- **Tigo / PMO City** — isolation tests green → incident closed, W2 todo
  resumed (spec 41 §8 → deltas Part 2). Deferred live tests (T6/T8/T9 +
  full T7 marker-tab replay) **executed 2026-08-22 23:2x–23:45 UTC — all
  GREEN** (slot untouched across storm cycles; markers never crossed users
  in either direction; same-user snapshot restore; fresh wake; archive
  sweep clean). The isolation class is now provably dead on the live fleet.
- DoD: D18 "session isolation regression suite green" box in
  `20-w2-dod.md`.
