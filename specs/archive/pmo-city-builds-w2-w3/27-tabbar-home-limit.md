# 27 — Tabbar: homepage-if-zero-tabs, Home/Plus icons, tab limit

> Status: **APPROVED (Tigo, 2026-08-21)** — decisions locked; implementation
> holds for explicit "go" (needs one Chrome restart per slot).
> Companion docs: `26-s7-fleet-app.md`, `21-w2-autonomy.md` §6 (decisions).

## Problem

Every fleet-slot start and every "Relaunch Chrome" opens a **new homepage
tab**: `slot-prepare-chrome.sh` passes `https://pmo.city` as the launch URL
(a homepage tab on *every* start), and restart-api's D5 tab-restore then
re-opens the snapshot on top — the snapshot already contains the homepage.
Result: homepage tabs piling up on the left. Kiosk has no native new-tab
strip, and memory favours a tab cap.

Root cause verified in code (2026-08-21): launch URL in
`slot-prepare-chrome.sh` + D5 restore in `restart-api.py` both add tabs.

## Decisions (Tigo, 2026-08-21)

1. Restore capped at the tab limit.
2. At limit: Home/Plus **disabled (grayed) with tooltip**.
3. Env names: **`HOME_URL`**, **`TAB_LIMIT`** (short, matches restart-api style).
4. Scope: **fleet slots AND the shared viewer** (consistent UX).
5. Plus popup: **inline popover in the bar**.

## S1 — Homepage tab only when zero tabs

- Remove the hardcoded `https://pmo.city` launch URL from
  `slot-prepare-chrome.sh` (Chrome then starts at newtab).
- restart-api (already owns boot/restore) decides the homepage:
  - restore path: snapshot exists → restore snapshot tabs (capped), **no
    homepage added**;
  - no snapshot / zero real tabs → open `HOME_URL`.
- Applies uniformly to `boot_restore`, `POST /restart`, and watchdog
  recovery (same code path).

## S2 — Home icon

- Position: **between Relaunch (⏻) and Back (←)**.
- Click → opens `HOME_URL` in a new tab. Disabled at the tab limit.

## S3 — Plus icon (URL new tab)

- Position: **last action button, right after Reload** (before the tab list).
- Click → inline popover anchored to the icon: URL field + OK/Cancel.
- Normalization: prepend `https://` when no scheme; accept http(s) only
  (other schemes → inline notice, no tab).
- Opens the URL in a new tab. Disabled at the tab limit.

## S4 — Tab limit

- `TAB_LIMIT` env, default **3**.
- Count = real http(s) tabs (`chrome://`, `about:`, extension pages
  excluded — same filter as `visibleTabs()`).
- Home/Plus disabled (grayed + tooltip "Tab limit reached (N)") when
  count ≥ limit. Closing a tab frees a slot.
- **D5 restore capped at `TAB_LIMIT`** (snapshot may hold up to 10).

## S5 — Compose variables

- `HOME_URL` (default `https://pmo.city`) and `TAB_LIMIT` (default `3`),
  added to the fleet compose env (slots) **and** the viewer compose env.
- The staged window-size fix (`--window-size=1920,1080`,
  `restore_on_startup=5`) lands in the same deployment.

## Config plumbing (MV3 constraint)

Extensions cannot read env vars. Design:

- `restart-api.py` gains **`GET /config`** → `{homeUrl, tabLimit}`, read
  from its own env (compose → container env → restart-api).
- Extension background fetches `/config` at startup (host permission for
  `127.0.0.1:9230` already present), caches in `chrome.storage.local`,
  falls back to built-in defaults if the fetch fails.
- `LIST_TABS` response extended with `tabLimit` so the content script
  checks the limit locally before Home/Plus.

## Files touched (at implementation)

| File | Change |
|---|---|
| `scripts/tabbar-extension/content.js` | Home + Plus buttons, popover, limit check, new order |
| `scripts/tabbar-extension/background.js` | /config fetch + cache, OPEN_URL message, LIST_TABS+tabLimit, EXT_VERSION bump |
| `scripts/tabbar-extension/manifest.json` | version bump |
| `scripts/restart-api.py` | GET /config, homepage-if-zero-tabs, restore cap |
| `scripts/26-s7-fleet-slot-prepare-chrome.sh` | drop launch URL |
| fleet compose raw + viewer compose raw | `HOME_URL`, `TAB_LIMIT` env |
| `hermes-cloudbrowser/spike/viewer-neko/prepare-chrome.sh` + tabbar copy | same changes (viewer) |
| specs: `27` (this), `21-w2-autonomy.md` §6, `26-s7-fleet-reproduction.md` | docs sync |

## Deployment / sequencing

- Loading the new extension requires **one Chrome restart per slot**
  (brief live-session drop) — needs Tigo's go for the deploy window.
- The previously staged window-size fix takes effect in the same restart.
- Verification after deploy: bar renders with new icons/order; homepage
  opens only on zero tabs (boot + relaunch); Home/Plus open tabs; limit
  gray-out at 3; restore capped at 3; `GET /config` returns correct values.

## Implementation record (2026-08-21, DONE)

Rolled out to fleet slots 1+2 and the shared viewer. All S1–S5 verified
live via CDP.

**Deployed files** (volumes `okixw2fxnwn1lakxvxajodww_scripts/_data` and
`4guplgcrvug7l7h64m2cxkm1_scripts/_data`): `restart-api.py`,
`tabbar-extension/{background.js,content.js,manifest.json}`,
`slot-prepare-chrome.sh` (fleet only). Compose raw (both services) and
Coolify env tables gained `HOME_URL`/`TAB_LIMIT` (raw, `is_literal:false`)
— effective at the next redeploy; the running containers use the built-in
defaults (same values) until then. Internal repo `98076e4`, template
mirror `7674178` (placeholders only).

**Verified live:**
- `GET /config` -> `{"ok": true, "homeUrl": "https://pmo.city",
  "tabLimit": 3}` on all three containers.
- S1: after clearing the stale duplicate-homepage snapshots and one
  `POST /restart` each, slot-1 and slot-2 sit at exactly **one**
  `https://pmo.city/` tab (no pile-up, no lingering newtab — the old
  launch URL had already produced 4x pmo.city tabs before the rollout).
- S2/S3: CDP-driven click test on slot-2 — Home opened a new pmo.city
  tab; Plus popover opened, URL submit opened `secrets.pmo.city` tab.
- S4: at 5 real tabs, `home.disabled === true`, `plus.disabled === true`
  (tooltip "Tab limit reached (3)"); freed by closing tabs.
- Restore cap: viewer (2 real tabs, snapshot kept) restored both through
  `POST /restart`; the snapshot (<= TAB_LIMIT) restores without homepage
  duplication.
- SW version: `EXT_VERSION === "1.5.0"` and `CONFIG.homeUrl/tabLimit`
  populated on all three (checked in the service-worker context;
  content-script globals are isolated from the page main world).

**Pitfall found (important for future deploys):** Chrome caches the MV3
service-worker script **per-profile** in
`$PROFILE/Default/Service Worker/ScriptCache`. After updating
`background.js` on disk, the running SW kept executing the OLD code
(slot-1/2 ran v1.4.0, viewer v1.2.0) even across Chrome restarts — the
manifest reported 1.5.0 while `EXT_VERSION` was stale. Fix applied: stop
Chrome, `rm -rf $PROFILE/Default/Service Worker` (the root-level
`Service Worker/` dir is vestigial — not the cache), start. Every future
tabbar `background.js` deploy MUST include this clear or the SW silently
runs stale code.

**Ops note:** `supervisorctl stop/start google-chrome` (manual admin
restart) does NOT trigger restart-api's restore — the browser parks at
newtab until `POST /restart` or a watchdog CDP-failure cycle. Use
`POST /restart` for planned restarts (it snapshots, restarts, restores).

---

## S6 — LRU eviction replaces the tab-limit block (2026-08-21, Tigo)

**Decision (Tigo):** at `TAB_LIMIT`, opening Home or a Plus URL must not
be blocked — the least-recently-used real tab is silently closed instead
(the active tab can never be the victim). Hover tooltips stay
informational ("Limit 3 — closes least-used tab"); a toast names the
closed tab for 4.5 s.

**Implementation (tabbar-extension v1.6.0, internal repo commit pending):**
- `background.js`: `evictLRU()` picks the victim by
  `chrome.tabs.Tab.lastAccessed` (Chrome 121+; active tab excluded),
  removes it, then creates the new tab; `openTab()` returns
  `{ok, url, evicted, evictedTitle}`. The submitting content script shows
  the toast from the **response** (no race with the new tab's load);
  `broadcastToast()` additionally fans the title out to settled tabs.
- `content.js`: Home/Plus are never disabled; `applyLimit()` only updates
  tooltips; new `#toast` element + `TAB_EVICTED` listener.
- `manifest.json` 1.6.0. `EXT_VERSION`/`VERSION` bumped in lockstep.

**Verified live (slot-2, CDP):**
- At exactly 3 tabs, Plus-open evicted the oldest (`example.com/alpha`),
  the new tab appeared, count stayed 3. Second pass: after activating
  `beta`, opening a new tab evicted `pmo.city` (oldest) while the active
  `beta` survived — LRU ordering by `lastAccessed` confirmed.
- Toast on the submitting tab: `Tab closed (limit 3): Example Domain`
  (`hidden:false`); buttons `home.disabled === false`, `plus.disabled ===
  false` at the limit, tooltips as decided.
- `EXT_VERSION === "1.6.0"` on all three containers (slot-1, slot-2,
  viewer) after the standard SW ScriptCache clear + `POST /restart`.

**S6 completion (v1.7.0, 2026-08-21, Tigo "go" after live repro of 6 tabs):**
- **Root cause found:** the limit only applied to tabs opened via the bar's
  own Home/Plus buttons (`evictLRU()` inside `openTab()`). In-page links
  that open a new tab (`target=_blank`, `window.open`) fire
  `chrome.tabs.onCreated` with **no listener** → count grew past
  `TAB_LIMIT` (Tigo reproduced 6 tabs at a limit of 3).
- **Fix (background.js):** `chrome.tabs.onCreated` + `onUpdated(url)`
  schedule a debounced (300 ms) `enforceLimit(newTabId)` that runs
  `evictLRU(skipId)` — the freshly-created tab is never the victim, the
  active tab is never the victim, and the LRU inactive real tab closes.
  The debounce absorbs the onCreated+onUpdated double-fire and page-settle
  updates so one tab never evicts twice. `trimExcess()` at SW startup
  removes pre-existing over-limit states (boot/snapshot restore or
  pre-fix leftovers) with a bounded loop. Same toast as S6.
- `manifest.json`/`EXT_VERSION`/`VERSION` → 1.7.0.
- **Verified live:** SW reports 1.7.0 on all three containers (SW
  ScriptCache cleared first — the spec-27 blocker; the viewer carries a
  second SW, the Vaultwarden extension, identified and excluded). Slot-1
  functional test via CDP `/json/new` (same path as `target=_blank`):
  starting at 1 tab, 4 native creations → count settled at exactly 3
  (limit), survivors = the 3 most recent, oldest evicted — LRU confirmed
  for native tabs. Post-test watchdog restart restored within the limit.

**Findings for the ledger:**
- W3 (watchdog-restore gap) — **FIXED 2026-08-21 (Tigo approval), live
  on all three containers.** The gap: when Chrome self-exits and
  supervisord auto-restarts it faster than the watchdog's `WATCHDOG_FAILS`
  streak, `_need_restore` never got set → browser parked at
  `chrome://newtab/` with zero tabs (observed after test traffic;
  recovered manually via `POST /restart`). The fix: the watchdog now
  tracks the Chrome main-PID via `/proc` and queues a restore on ANY
  `pid` change (supervisord auto-restart, manual start, crash loop),
  regardless of the failure streak; `restore_tabs` stays no-op when tabs
  are already present. `_chrome_main_pid()` excludes `--type=` renderer
  processes; the PID baseline is re-established in `main()` after waiting
  for Chrome to come up, so a restart during startup isn't misread as a
  change. Verified live on slot-2: SIGKILL'd the main Chrome process →
  `watchdog: chrome pid changed 11302 -> 12027, queueing restore` →
  `tab-restore: opened 1 tab(s) from snapshot` → pmo.city back with NO
  `POST /restart`; exactly one restore fired (no loop); other containers
  healthy. restart-api.py updated in-repo (commit pending); script
  volumes deployed on all three.

**W3 backlog (low priority, Tigo 2026-08-21):**
- cdp-relay log hygiene: `pipe()`'s log lines call `getpeername()` on
  dead sockets during Chrome restarts → Python traceback spam in the
  container logs (the data path is unaffected — relay self-heals; it's
  purely log noise that buries real signals and grows log volume during
  restart windows). Fix: guarded `peer_name(sock)` helper returning "?"
  instead of raising. ~15-30 min incl. verification.
- Test tooling: `/json/new` needs **PUT** (GET → 405); the HTTP
  `/json/list` endpoint does NOT expose `lastAccessed`/`active` (the
  extension `tabs` API does — eviction proves it); rapid CDP churn on a
  kiosk slot can trip the watchdog (recovery self-heals).
