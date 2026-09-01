# 58 — Tab-loss incident: session tabs not preserved (2026-08-25)

Status: root-cause documented · W3-7 hardening implemented and regression-tested (2026-08-31)

## Report (Tigo)

> "I had three tabs, and now it reopened only with one tab, the Vaultwarden
> tab. That's not right."

## Evidence (slot-1, spike-user@aikumi.pro)

- Archive snapshot at suspend (ts 1787650417 = 09:33:37 UTC):
  `{"urls": ["https://secrets.pmo.city/#/lock"]}` — **1 URL only**.
- Restore: `tab-restore: opened 1 tab(s) from snapshot` — the restore
  mechanism worked exactly as designed; the snapshot it read had 1 URL.
- Live tab list at ~09:26 (during the user's session): `[Aikumi News,
  Vaultwarden #/vault]` — 2 tabs, vs the user's 3.
- At suspend (09:33:37), Chrome had only the vault tab left; the other
  tabs were closed **before** the suspend snapshot ran.

## Root cause

**The other tabs were evicted/closed before suspend; the snapshot then
faithfully captured the remaining 1 tab.** Two compounding factors:

1. **Tab-limit LRU eviction (tabbar extension, background.js `evictLRU`)**
   — at `TAB_LIMIT=3`, opening a new tab evicts the least-recently-used
   real tab. During the user's live session, agent probing (CDP
   `Target.createTarget`) opened extra tabs (e.g. a second vault tab
   while the real one sat on the SSO redirect, which does not match the
   `secrets.pmo.city` host filter) → count exceeded 3 → the extension
   evicted the user's real tabs (Aikumi News etc.).
2. **Snapshot timing** — the only snapshot source is `snapshot_tabs()`
   (watchdog, gated on `chrome_owns_profile()` pid-match — O8, spec 43 —
   plus the pre-suspend snapshot in `do_suspend`). Once the tabs were
   evicted, no later snapshot could resurrect them.

**This is an agent-discipline incident (live-session probing created
tabs), amplified by the LRU eviction design.** The restore pipeline
itself (snapshot → archive → restore) was correct.

## Fixes

1. **Agent rule (binding):** never `Target.createTarget` / open tabs in a
   **live human session**. All probing must be read-only (attach +
   evaluate) or use an isolated context. If a new tab is unavoidable,
   close it immediately after use and re-snapshot.
2. **Hardening (candidate, W3):** eviction could exempt the active user's
   tabs from agent-created eviction pressure — impractical to
   distinguish; simpler: raise `TAB_LIMIT` headroom or make the
   extension never evict a tab older than N minutes (age floor).
3. **Hardening (implemented in W3-7):** pre-suspend snapshot still captures
   the freshest state, and `restart-api.py` also persists an independent
   `tab-snapshot.last-good.json` copy. The copy is atomically replaced only
   after a validated snapshot and is used only when the live JSON is malformed
   or unreadable; a valid empty workspace remains authoritative.

## Evidence artifacts

- `/data/sessions/spike-user@aikumi.pro/profile/tab-snapshot.json` (1 URL)
- restart-api log: `tab-restore: opened 1 tab(s) from snapshot`
- restart-api code: `snapshot_tabs()` (L1019), `do_suspend` pre-suspend
  snapshot (L664), watchdog gating (L1219-1221), extension `evictLRU`
  (background.js L90).

## Tooling

- `/opt/data/cb-pm-*.py` probes — read-only attach/evaluate only from
  now on; no createTarget during live sessions.

## Open Browser availability regression (2026-09-01)

- `scripts/test-router-queue-open-browser.py` — **4/4 PASS**.
- The regression covers a stale `backed_off` record coexisting with a newer
  `waiting` or `offered` record for the same user. The current queue record is
  selected first, so a valid offer exposes `open_url` and its countdown.
- The production test filename follows the CloudBrowser convention:
  `test-<component>-<behavior>.py`.

## W3-7 verification (2026-08-31)

- Focused test: `scripts/test-w3-7-last-good-snapshot.py` — **7/7 PASS**.
- Covered: atomic dual-write, malformed-live fallback, valid empty state,
  richer-state backfill, live-state precedence, Authentik filtering, and
  owner-mismatch cleanup of both copies.
- No live fleet deployment was performed as part of this change.
