# Spec 49 — Session-Leak Incident: Wrong User's CloudFiles in Kiosk

> **Severity: HIGH — security (cross-user data leak).**
> **Status: INVESTIGATED → FIXED & DEPLOYED (spec 48 rev2) → REPO SYNCED (this commit).**
> Date: 2026-08-23 · Discovered by: Tigo (screenshot of montigaud's kiosk) · Reported to: PMO City (this repo)

## 1. Summary

Slot-1's owner was `montigaud@aikumi.pro`, but the kiosk Chrome showed
**`CloudFiles: spike-user@aikumi.pro`** — the downloads area of a *different*
user rendered inside montigaud's session. Tigo: *"This is a big, big, big
bug… one profile per user… document this, document the fix, fix, deploy,
restart, everything as needed."*

Investigation proved this was **NOT a Chrome profile leak** (the profile
isolation chain held; see §3) — the leak lived in the **open-url / tab-restore
machinery** (the rev1 `_pending_goto` mechanism introduced by spec 48 rev).
A queued user's *intent to open CloudFiles* was persisted without an owner
check and replayed inside the *slot owner's* kiosk; the kiosk then polled
`/api/files`, which resolved via tinyauth to **the slot owner = spike-user**,
rendering spike-user's files in montigaud's session.

## 2. Timeline of evidence (2026-08-23, UTC)

| Time | Event | Evidence |
|---|---|---|
| ~18:57 | Tigo reports kiosk shows `CloudFiles: spike-user@aikumi.pro` while slot-1 owner is montigaud | Tigo screenshot |
| — | spike-user's queue-page pill click → `POST /queue/goto` stores pending-goto → `https://cloudfiles.dev01.pmo.city/` (keyed by email only) | router rev1 code (`_pending_goto`) |
| — | montigaud's session pill → `POST /kiosk/open?url=cloudfiles…` opens CloudFiles in the kiosk | router log |
| — | Tab-restore snapshot `{"ts":1787514204,"urls":["https://cloudfiles.dev01.pmo.city/"]}` → opens spike's CloudFiles URL in montigaud's kiosk | `tab-snapshot.json` (montigaud archive, purged §6) |
| — | Kiosk polls `/api/files`; tinyauth resolves identity → **spike-user** (529 CF hits as spike vs 62 as monty in last 60 min) | downloads-api access log |
| 19:12–19:13 | **Fix deployed hot** — router container running rev2-final (`/queue/goto` + `_pending_goto` removed, `grep -c pending_goto /app/router.py` = 0) | container md5 `ade2690d` |

## 3. What held (safe layers verified)

- **Chrome profile isolation: airtight.** `do_wake` stopped Chrome on
  user-switch, restored montigaud's own 144 MB archive; live cookies were
  montigaud's `tinyauth-session-39fcd0f6`, **not** spike's `__cf_bm`.
- **downloads-api per-user isolation: airtight.** Tested `tigo-test@x.pro`
  against slot-1 owned by montigaud → `[]` (empty), no leak.
- Per-user archive/restore with owner marker (`.archive-user.json`) +
  contamination refusal (spec 42) held throughout.

## 4. Root cause (chain of 3 + identity resolution)

1. **rev1 `_pending_goto` was keyed by email but unowned at replay time** —
   the *queue-page* click (spike, queued) stored an intent that was later
   consumed by *kiosk-open* (montigaud, active) without any ownership check.
2. **Tab-restore replayed the stored URL inside the slot owner's kiosk** —
   the snapshot's URL became a live tab in montigaud's session.
3. **`/api/files` identity = slot owner, not the URL's originator** — the
   kiosk rendered *spike-user's* area inside *montigaud's* session. The
   files themselves were not cross-read (each poll was authorized as the
   slot owner), but the *presentation* crossed users.

**Fix principle (spec 48 rev2):** remove the pending-intent mechanism
entirely. CloudFiles + Secrets are **always plain main-browser links**
(`target=_blank`) — files must be downloadable on the main computer; inside
the kiosk there is no way to get a file out. Only the **GrantHub Shared**
pill enters the kiosk (goto param at offer-take), where capture is the
intended purpose. Queue bar hides the GrantHub pill (no kiosk yet).

## 5. Fixes applied

1. **spec 48 rev2 (code, deployed 19:12–19:13 UTC):** removed `_pending_goto`
   + `POST /queue/goto` from `router.py` (rev2-final, md5 `ade2690d`);
   `title-proxy.py` (md5 `96a7d958`) serves CloudFiles/Secrets as plain
   links on all 4 surfaces; queue+landing bars `target=_blank`; only
   GrantHub Shared carries `goto`.
2. **sso-broker hardening:** broker re-reads the slot owner on each capture
   pass (was: once at startup) — closes the "tag-along spy" case where the
   broker stays armed for the *previous* slot owner.
3. **Stale snapshot purged:** `montigaud@aikumi.pro/profile/tab-snapshot.json`
   (contained the spike CloudFiles URL) deleted from the sessions volume.
4. **Repo sync (this commit):** `router.py`, `title-proxy.py`,
   `test-router.py` brought byte-identical to deployed
   (`ade2690d` / `96a7d958` / test-router updated for rev2 semantics).

## 6. Verification

- **Live, all 4 surfaces** (commit `f97185f`): session bar Secrets = plain
  link + CloudFiles = `/kiosk/open`… → rev2 semantics confirmed:
  CloudFiles/Secrets plain main-browser links, GrantHub Not Shared red
  `/connect`, Shared green.
- **Harness:** 99/104 — the 3 remaining failures are **pre-existing spec 41
  timing flakes** (D/E restart scenario; identical on committed HEAD;
  cause: missing `/etc/hosts` `slot-1 → 127.0.0.1` mapping on the dev box,
  documented in test-router.py header). Not regressions from this fix.
- **Fleet state post-cleanup:** users = {spike-user}, slots = {1:
  spike-user}, queue = spike-user2, spike-user, montigaud only.

## 7. Follow-ups

- `/etc/hosts` slot-1 mapping on the dev box to un-flake the 3 spec 41
  tests (needs root).
- W3 watchdog `tab-snapshot.json` pid-match gating (O8, parked) — snapshot
  should be taken from the live profile regardless of pid-match, with owner
  marking; isolation unaffected but reviewed in W3.
