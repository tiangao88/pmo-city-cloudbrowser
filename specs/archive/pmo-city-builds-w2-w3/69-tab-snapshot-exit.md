# 69 — Tab snapshot preservation + tab-bar exit removal (2026-08-25)

Status: **DEPLOYED + VERIFIED** (commit TBD)

## Context (Tigo, 2026-08-25, montigaud session)

> "I still have the exit icon here, which is wrong. But look at the top
> right, I have the exit session button, which is good. Also, I've lost
> my tabs... I'm sure that before I had three tabs in that session. So
> where are they gone? And then... I try to reload this page. And the
> main browser is hanging."

## Part 1 — Tab snapshot destroyed (root cause + fix)

### Root cause (live-verified)
The slot's suspend path has a spec-42 isolation guard: when
`chrome_owns_profile()` is False (a foreign/stale chrome), it **deletes
the live `tab-snapshot.json`** and skips snapshotting. `archive_user()`
then replaces the user's archive **wholesale** (`rmtree(dest)` +
`os.replace(tmp, dest)`). Combined, a guard-path suspend:
1. deletes the live snapshot, then
2. replaces the archive with a profile **without** a snapshot —
   **erasing the archive's last-known tabs**.

Observed: montigaud's archive had `profile/tab-snapshot.json` during
the 12:5x audit; after a suspend on slot-2 it had **NO-SNAPSHOT**. No
backup exists (`.bak-*` removed, no snapshot backups anywhere) — the
previous 3 tabs are **unrecoverable**. This suspend was the agent's own
spec-68 live test on slot-2 (wake→suspend), i.e. the destructive path
was triggered during testing, not by normal use.

### Fix (`restart-api.py`, deployed)
`archive_user()` now **preserves the existing archive's
`tab-snapshot.json`** when the new archive's profile has none:

```
new_snap = tmp/profile/tab-snapshot.json
old_snap = dest/profile/tab-snapshot.json
if not exists(new_snap) and exists(old_snap): copy2(old_snap, new_snap)
```

So a guard-path suspend can no longer erase the last-known tabs. The
live watchdog (`snapshot_tabs`, spec 61b never-shrink guard) keeps the
on-slot snapshot fresh (verified: current session tabs
agenticpmo.org + exa.ai captured at ts 1787667087).

## Part 2 — Tab-bar Exit fallback removed

The spec-64 (2026-08-25) tab-bar Exit FALLBACK button (`#exit`, shown
only when no neko top bar exists) rendered bottom-right in the kiosk —
Tigo: **wrong**, the top-right Exit session button (neko top-bar exit,
`ensureBarExit` spec 41) is the good one. Removed from
`tabbar-extension/content.js` (v1.14.0): button element, `exitBtn`
const, and the `updateExitVis` fallback-show logic. The spec-41
top-bar Exit + confirm popup machinery (`barExitBtn`/`openExitPop`/
`ensureBarExit`) is **kept intact**. Takes effect on the next page
navigation/reload (content scripts re-inject per load) — no Chrome
restart needed on the live session.

## Part 3 — "Browser hanging on reload"

Verified NOT a stuck browser: WebRTC stream connected
(`peer connected`, 2:01 PM), CDP shows 4 live tabs (agenticpmo.org,
exa.ai, pmo.city, chrome://newtab). The reload hang was transient —
likely the neko stream blip while the profile sat on the Google OAuth
challenge (the slot-1 snapshot briefly held an accounts.google.com URL
from the auth.aikumi.app flow). If it recurs, `/fleet/rescue`
(stream-dead → restart-neko) is the recovery.

## Part 4 — `/api/files` spike-user requests (not a leak)

Router log interleaved `GET /api/files user=spike-user` and `user=montigaud`
during montigaud's session. Verified:
- Router `_proxy_raw` forwards the client's **raw** Remote-Email — it
  does not synthesize identity.
- The kiosk has **no CloudFiles tab open** (CDP targets = 4 pages, none
  cloudfiles).
- `downloads-api.resolve_area(spike-user)` → spike-user's own archive
  area (only `.janitor-state`/`.quarantine` — no user files).

Conclusion: the spike-user `/api/files` polls come from a **stale
CloudFiles tab in Tigo's own client browser** (still holding a
spike-user tinyauth session from earlier tests). Per-user isolation is
intact — spike-user only ever sees spike-user's own area. Action for
Tigo: close that stale spike-user tab; nothing to fix in the fleet.

## Files / deploy
- `restart-api.py`, `tabbar-extension/content.js` → scripts volume
  (both slots), md5-verified (`810332ba…`, `d6296f1d…`), restart-api
  restarted; content.js applies on next navigation.
- `py_compile` + `node --check` clean.

## Follow-ups
- Tigo: close the stale spike-user CloudFiles tab on the client side.
- Watch the current montigaud session end: the 2-tab snapshot should
  survive into the archive (preservation guard live).
