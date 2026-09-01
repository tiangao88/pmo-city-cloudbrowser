# Spec 41 — Session Isolation Incident: Cross-User Profile Contamination

> **Severity: HIGH — security (cross-user data leak).**
> **Status: UNDER INVESTIGATION → FIX SPEC WRITTEN (spec 42) → PATCHED & VERIFIED (see §7).**
> Date: 2026-08-22 · Discovered by: Tigo (spike-user session) · Reported to: PMO City (this repo)

## 1. Summary

A **cross-user session leak** was found on the cloud-browser fleet: a web page
(PMBOK on Wikipedia) opened in the **spike-user** kiosk session also appeared
in the **montigaud** session. Investigation proved the mechanism: during a
**wake storm** (repeated `/wake` calls on a slot whose Chrome never
restarted), the **profile on disk was swapped between users underneath a live
Chrome process**, so a suspend snapshot captured the *wrong user's* tabs and
archived them into the *other user's* archive. Tabs and browser history
leaked across user boundaries; the same vector would carry cookies/session
state for any real service a user was logged into.

**Root cause: two interacting bugs (spec 42):**
1. `restart-api.py do_wake()` restores the user archive onto the slot profile
   **without stopping Chrome first** — when Chrome is already running (the
   router's offer pre-wake), the running process keeps user A's tabs while
   the disk profile is swapped to user B.
2. Router pre-wakes slots at **offer time** (`_offer_wake`), not at take
   time — the 60 s offer grace + re-offer cycle produces a storm of `/wake`
   calls alternating between queue heads, each triggering the bug-1 swap.

## 2. Timeline of evidence (2026-08-22, UTC)

All times UTC. Slot-1 = `slot-1-okixw2fxnwn1lakxvxajodww`.

| Time | Event | Evidence |
|---|---|---|
| 18:05:33 | spike-user takes slot-1; opens pmo.city, Wikipedia, then PMBOK at 18:08:03 | router log; spike-user archive `History` |
| 18:20:46 | spike-user released (expired) → suspend: chrome stopped, archived (4 KiB), profile wiped | slot-1 log `idle: archived spike-user` + `slot profile wiped` |
| 18:20:51 | montigaud takes slot-1 → restore montigaud, chrome started | slot-1 log `restored montigaud` |
| 18:36:04 | spike-user2 takes slot-1 (montigaud released at 18:36:00) | router + slot-1 logs |
| 18:51:12 | spike-user2 released; **spike-user restored**; chrome started (pid 15237); watchdog reopens 1 tab from snapshot = **PMBOK** | slot-1 log `restored spike-user`, `tab-restore: opened 1 tab(s)` |
| 18:51–19:20 | **WAKE STORM**: router alternates `/wake` spike-user ↔ montigaud every ~60 s (offer grace cycle). Each wake: `restore_user()` wipes profile + copies archive, then `chrome started: ERROR (already started)` — **Chrome pid 15237 never restarts** | slot-1 log (repeated), router log (offer/expire alternation) |
| 19:20:49 | montigaud takes slot-1 (offer taken) → wake montigaud → profile swapped to montigaud's archive, **Chrome still pid 15237 (spike-user's)** | router log; slot-1 log |
| 19:26:14 | slot idle-suspends: `snapshot_tabs()` via CDP reads **running Chrome = spike-user's** → PMBOK captured; `archive_user(montigaud)` writes PMBOK **into montigaud's archive**; chrome stopped (kills pid 15237) | slot-1 log: `SUSPEND user=montigaud`, `killing google-chrome (pid 15237)` |
| 19:26:22 | montigaud restored from **contaminated archive**; chrome restarts; watchdog reopens PMBOK from snapshot | slot-1 log |
| 19:26:54 | **montigaud's History records its only PMBOK visit** (leak persisted into his live session) | montigaud archive `History` + live slot-1 `History` |
| 19:41:53 | spike-user's archive History gains a second PMBOK visit (19:41 handover) — bidirectional contamination | spike-user archive `History` |
| ~19:50 | **Tigo notices** the PMBOK page in the montigaud session (opened in spike-user session) → reports | — |
| 20:0x | Investigation: fleet state, both archives' `History`, `tab-snapshot.json`, slot-1 + router logs, `restart-api.py`/`router.py` code | this doc |

## 3. Mechanism (confirmed, not hypothesized)

```
offer cycle (60 s grace)                do_wake(user) on slot
─────────────────────                   ─────────────────────
queue head A offered ──/wake A──►      restore_user(A): wipe profile, copy A's archive
offer expires (no take)                 supervisorctl start chrome → "ERROR (already started)"
queue head B offered ──/wake B──►      restore_user(B): wipe profile, copy B's archive
offer expires                          chrome STILL RUNNING = user A's process/tabs
... storm repeats ...
user B finally takes ────────────►     slot thinks B (disk = B), Chrome = A (tabs from A)
suspend (idle)                          snapshot_tabs() reads A's tabs  ← THE LEAK
                                        archive_user(B) writes A's tabs into B's archive
next wake(B)                            B's restored session shows A's tabs (PMBOK)
```

## 4. Impact assessment

| Channel | Leaked? | Evidence | Risk |
|---|---|---|---|
| Open tabs | ✅ YES | PMBOK tab visible in montigaud live session; montigaud History visit 19:26:54 | **HIGH** — direct cross-user visibility |
| Browser history | ✅ YES | montigaud archive contains spike-user's PMBOK visit; spike-user archive contains montigaud traces (aikumi.news in Safe Browsing/cache files) | HIGH |
| Cookies | ⚠️ partial | montigaud archive now carries `wikipedia.org` cookies; spike-user archive carries `aikumi.news` traces | **HIGH vector** — if either user had been logged into a real service (CRM, vault, bank), those session cookies would have crossed too |
| Downloads / files | ⚠️ plausible | same restore/archive path moves `Downloads/`; no evidence of file leakage observed, but the mechanism does not exclude it | MEDIUM |
| Credentials (passwords/keys) | not observed | no login state observed crossing | n/a — but vector exists |

**Attribution note:** this is a **plumbing/state-machine bug**, not an
intentional actor. The contamination is between *test* users (spike-user,
spike-user2, montigaud — all controlled by Tigo/PMO City). No external party
is implicated.

## 5. Contaminated archives (cleanup targets)

- `montigaud@aikumi.pro` — PMBOK in `profile/tab-snapshot.json`, `History`,
  `Sessions/Tabs_*`, `Favicons`; wikipedia.org cookies.
- `spike-user@aikumi.pro` — aikumi.news traces (cache/Safe Browsing), PMBOK
  re-visit at 19:41:53, wikipedia cookies from montigaud's era.
- `spike-user2@aikumi.pro` — no contamination found (empty snapshot; no
  foreign URLs).

## 6. Immediate containment (already done)

1. **Slot-1 live session**: PMBOK tab **closed** in the live montigaud
   session (20:0x). The snapshot file was regenerated without it on next
   snapshot.
2. **No new sessions granted during investigation** (single slot fleet;
   montigaud remains the only active user).
3. Findings + this doc recorded in repo (visible, per Tigo).

## 7. Remediation (spec 42 — fix, spec 43 — tests)

- **Fix A** `do_wake()`: stop Chrome (and title-proxy) **before** restoring
  a *different* user's archive; skip restore entirely when re-offered the
  same user. Chrome must never run across a profile swap.
- **Fix B** `do_suspend()`: snapshot only if the running Chrome PID matches
  the PID started at wake; on mismatch, skip snapshot + clear stale
  snapshot (never archive another user's tabs).
- **Fix C** router: **remove the offer-time pre-wake** (`_offer_wake`);
  wake the slot only when the offer is **taken** (session start). The
  60 s offer/expire cycle then never touches the slot.
- **Fix D** defense-in-depth: write `.archive-user.json` (user + ts) into
  every archive; `restore_user()` refuses/repairs on mismatch.
- **Fix E** purge contaminated archives per §5.

**Verification** (spec 43): wake-storm regression harness + live two-user
isolation test + normal suspend/resume regression. DoD gains an isolation
checklist item (D18).

## 8. References

- Spec 42 — session isolation fix: `42-session-isolation-fix.md`
- Spec 43 — session isolation tests: `43-session-isolation-tests.md`
- Code: `restart-api.py` (slot) + `router.py` (fleet) — fleet scripts volume
  `okixw2fxnwn1lakxvxajodww_scripts`
- Related: spec 29 (idle suspend/resume), spec 31 (queue + session limits),
  spec 36 (offer grace), spec 41 note in router.py comments.
