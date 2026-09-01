# 61 — Tab-loss: eviction pressure + homepage race (once and for all) (2026-08-25)

Status: **IMPLEMENTED → DEPLOYED → LIVE-VERIFIED** (commit `266fe33`) · W3-7 durable last-good snapshot extension regression-tested 2026-08-31

## Problem (Tigo, 2026-08-25)

> "Is the session-saving bug fixed when the session ends?" — and after
> evidence: "Yes, do everything necessary to fix this problem once and
> for all."

Tab-loss evidence live on slot-1 (spike-user session):
- Archive at suspend preserved all 3 tabs; restore opened 3.
- Then the homepage (`pmo.city`) joined the tab set → count 4 >
  TAB_LIMIT=3 → LRU eviction closed the user's real tabs (connect,
  secrets) BEFORE the session-end snapshot → live snapshot dropped to
  1 URL → next suspend would save only PowerMail.

Root cause chain (same class as spec 58, now understood end-to-end):
1. The homepage must be a zero-tabs fallback ONLY, but `ensure_homepage()`
   ran even when a restore had just populated tabs (it checked
   `page_urls()` which momentarily saw the browser mid-restore) →
   homepage joined restored tabs.
2. At the tab limit, LRU eviction closed ANY least-recently-used tab —
   including long-lived user tabs (vault, inbox) — the moment anything
   new opened.
3. External opens could duplicate an already-open surface, multiplying
   tab count and feeding eviction.
4. Restore could run twice for one Chrome start (boot restore + watchdog
   pid-change queue), duplicating the whole tab set.

## Fixes (all deployed)

**tabbar-extension/background.js v1.13.0:**
1. **Age floor** — `EVICT_AGE_FLOOR_MS = 10 min`: never evict a tab the
   user kept open past the floor. Eviction now only ever touches young
   tabs (freshly opened / newly created), which are exactly the
   eviction's intended targets (new work at the limit). User state
   (vault, inbox, CRM) survives to the session-end snapshot.
2. **openTab dedupe** — opening a URL that already exists (same origin
   path, fragment-insensitive) focuses the existing tab instead of
   creating a copy. No more duplicate surfaces feeding eviction.

**restart-api.py (spec 61):**
3. **Homepage never during/after restore** — `ensure_homepage()` defers
   when a restore or pending start is in flight (`_need_restore` /
   `_pending_start_url`) and re-checks later (`_homepage_after_restore`,
   45 s budget): opens ONLY if the browser is STILL at zero real tabs.
   The homepage can never join a restored tab set again.
4. **Restore runs once per Chrome start** — new `_restore_done` flag:
   set at the end of a real restore; reset on every Chrome start
   (`record_chrome_start`, `clear_chrome_start`, watchdog pid-change).
   A queued second restore no-ops (no duplicate tab set).
5. **Snapshot hygiene** — `snapshot_tabs()` dedupes URLs and keeps only
   http(s); duplicates no longer multiply the restore count.

## Verification (live, slot-1)

- `tab-restore: boot restore (browser at empty state)` →
  `tab-restore: opened 1 tab(s) from snapshot` → tab list = exactly the
  snapshot URL (PowerMail) — no homepage, no duplicate.
- Watchdog pid-change queue fired after the restore → no-op (restore_done
  guard) — no second restore.
- Extension service worker loaded from the volume (v1.13.0 background)
  after Chrome restart.
- Router harness unchanged: **109/109 PASS**.
- Deployed to `okixw2fxnwn1lakxvxajodww_scripts` volume; slot-1 + slot-2
  restart-api restarted; slot-1 Chrome restarted (extension reload).

## Notes

- Root `/opt/data/background.js` was a STALE copy (pre-v1.11/v1.12) —
  the deployed extension is `tabbar-extension/background.js`. Synced to
  avoid future confusion. Lesson: the extension lives in
  `tabbar-extension/`, not at the repo root.
- Dual-snapshot (persist last-good watchdog snapshot separately) remains
  a W3 candidate; with the age floor + homepage defer the eviction
  vector is closed, so the snapshot content itself is now trustworthy.

## Files

- `scripts/tabbar-extension/background.js` (v1.13.0)
- `scripts/restart-api.py`
- `specs/61-tab-loss-hardening.md`

## 61b addendum (2026-08-25, live 3→1 recurrence) — ROOT CAUSE + fixes

Tigo: "I had 3 tabs in spike-user session and restore only brought back 1."

Live evidence: `tab-restore: opened 3 tab(s) from snapshot` (good restore),
then my spec-61 deployment restarted restart-api + Chrome mid-session;
the next restore read a **1-URL snapshot** → 2 tabs lost.

Two compounding defects (both fixed):
1. **Snapshot race** — a watchdog pass landing mid-restore (only 1 of 3
   tabs loaded yet) OVERWROTE the good 3-URL snapshot with a 1-URL one.
   Fix A: `snapshot_tabs()` never shrinks a richer snapshot younger than
   `SNAPSHOT_STALE_S=300` (keeps it, logs "KEPT richer snapshot").
   Fix B: the watchdog snapshots ONLY after `_restore_done` — i.e. once
   the restore for THIS Chrome start completed (no mid-restore writes).
2. **restart-api restart froze snapshotting** — `boot_restore()` assigned
   `_restore_done = True` WITHOUT a `global` declaration → no-op local →
   the module flag stayed False → the watchdog's `if _restore_done:` gate
   never opened → snapshots stopped updating until the next Chrome start.
   Fix: `global _restore_done` in boot_restore; audited ALL flag
   assignments for missing globals (script check — all clean).

Verified live on slot-1: 3 tabs opened → snapshot holds all 3 → Chrome
restart → `tab-restore: opened 3 tab(s) from snapshot` → all 3 restored
(connect, secrets, PowerMail). Harness still 109/109.

## W3-7 durable last-good extension (2026-08-31)

`restart-api.py` now writes `tab-snapshot.json` and an independent
`tab-snapshot.last-good.json` atomically. The live snapshot remains
authoritative when valid, including a valid empty workspace; fallback occurs
only for malformed or unreadable live state. The owner-isolation teardown
clears both copies. Focused coverage is
`scripts/test-w3-7-last-good-snapshot.py` — **7/7 PASS**.

This source change is regression-tested but has not been deployed to the live
fleet.
