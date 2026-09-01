# Spec 44 — O6: Tab bar on error pages (v1.12.0)

**Status:** ✅ IMPLEMENTED + DEPLOYED + LIVE-VERIFIED 2026-08-22 (slot-2)
**Item:** W2 todo row 1 / §E open item O6 (2026-08-21 incident:
`ERR_CONNECTION_RESET` → restart button unreachable exactly when Chrome broke)
**Files:** `scripts/tabbar-extension/{manifest.json,background.js,content.js,error.html,error.js}`
**Commit:** `79ed0c4` (extension) — this spec + deltas follow

## Problem

`chrome-error://chromewebdata/` pages (failed navigations) **cannot run
content scripts** — neither manifest-declared content scripts nor
`chrome.scripting.executeScript` are permitted on them. The tab bar
(and with it the relaunch/back/reload affordances) was therefore absent
precisely on the pages a kiosk user lands on when the network breaks
(2026-08-21: ERR_CONNECTION_RESET left the user stuck until idle-suspend).

## Design: replace, don't script

Injection being impossible, the reliable pattern is to **replace the
error page with a bundled extension page** (`error.html`) that shows the
failure + a full functional tab bar. An extension page has full
`chrome.tabs` API access, so the bar is *more* capable than the injected
one, not less.

### background.js — `webNavigation.onErrorOccurred` listener

```js
chrome.webNavigation.onErrorOccurred.addListener((details) => {
  if (details.frameId !== 0) return;                 // main frame only
  if (typeof details.tabId !== "number" || details.tabId < 0) return;
  if (details.error === "net::ERR_ABORTED") return;  // user stop / redirect
  if (!/^https?:\/\//i.test(details.url)) return;    // web targets only
  const target = chrome.runtime.getURL("error.html") +
    "?u=" + encodeURIComponent(details.url) +
    "&e=" + encodeURIComponent(details.error || "net::ERR_FAILED");
  chrome.tabs.update(details.tabId, { url: target }).catch(() => {});
});
```

### Pitfalls handled (all verified in code + live)

| Pitfall | Handling |
|---|---|
| `ERR_ABORTED` fires for **every** user-cancelled/redirected navigation (stop button, downloads, redirect chains) — hijacking those breaks normal browsing | filtered out explicitly |
| Subframe failures (ads, embeds) happen constantly | `frameId === 0` only |
| Redirect loop (our own page re-triggering the listener) | `error.html` is `chrome-extension://` → excluded by the http(s) check |
| Tab closed mid-flight | `tabs.update(...).catch()` |
| `tabId === -1` (some prerender/background events) | guarded |

### error.html / error.js

- Dark card matching the bar tokens (`rgba(17,17,19,.92)` bar,
  `#e8e8ea` text, 12px system-ui): ⚠ icon, "This page couldn't be
  loaded", the failed URL, a **friendly** one-liner for common
  `net::ERR_*` codes (DNS, refused, reset, timeout, TLS/cert, redirects;
  unknown codes fall back to the raw code), and buttons **↻ Retry**
  (primary — navigates the tab back to the failed URL),
  **← Back** (`chrome.tabs.goBack`), **⌂ Home** (`OPEN_HOME`, same
  semantics as the main bar).
- Bottom tab bar (26px, same look as the content-script bar): tab pills
  (switch/close, >1 tab), relaunch ⏻, back ←, forward →, reload ↺,
  home ⌂. **Same message protocol as content.js** (`LIST_TABS` /
  `SWITCH_TAB` / `CLOSE_TAB` / `OPEN_HOME` / `NAV_BACK` / `NAV_FORWARD` /
  `RELOAD_PAGE` / `RELAUNCH`) → the service worker needed **zero new
  handlers**. Pills poll every 1.5 s (same cadence as content.js).
- Retry is guarded to http(s) targets (the listener only ever sends
  those; manual page opens fall back to about:blank).

### manifest / version

- `permissions` + `"webNavigation"`; version → **1.12.0**
  (background.js `EXT_VERSION`, content.js `VERSION` bumped in sync —
  healTabs probes `EXT_VERSION`; a mismatch would re-inject on every
  tab forever). content.js has no functional change (error pages can't
  run it anyway); the bump is purely for the version probe.

## Live verification (2026-08-22, slot-2 — free slot, Chrome restarted to load v1.12.0)

| Check | Result |
|---|---|
| `https://o6-does-not-exist-zzz.invalid/` (instant NXDOMAIN) | `ERR_NAME_NOT_RESOLVED` → error.html replaced the page **<1 s** (poll 0) |
| Error card content | URL + "The server address could not be found (DNS)." + Retry/Back/Home ✓ |
| Tab bar on error page | 2 pills (error tab + the not-yet-replaced chrome-error tab), 7 buttons (5 nav + 2 close) ✓ |
| Pill switch | clicked non-active pill → `chrome://new-tab-page/` became active ✓ |
| `ERR_CONNECTION_TIMED_OUT` (192.0.2.1, blackholed) | eventual replacement with `e=net::ERR_CONNECTION_TIMED_OUT` ✓ (proves the listener keeps waiting for the real failure; playwright's 15 s goto cancel was correctly NOT treated as abort) |
| Re-verify (fresh attach) | `bRelaunch: true`, retry label `↻ Retry`, bar present ✓ |
| `ERR_ABORTED` filter | playwright goto timeout → tab stayed on native chrome-error until the *real* TIMED_OUT arrived (abort never hijacked it) ✓ |

Residue: two test error tabs closed; slot-2 back to `chrome://new-tab-page/`.

## Deploy

- Files scp'd to the shared scripts volume
  (`/var/lib/docker/volumes/okixw2fxnwn1lakxvxajodww_scripts/_data/tabbar-extension/`),
  byte-identical to repo (md5 verified), chmod 644 / uid 1000 (the two
  NEW files landed `640 root:root` on first scp — the classic umask
  pitfall; fixed immediately; `cb-normalize.timer` self-heals anyway).
- Slot-2 Chrome restarted → v1.12.0 loaded (verified by behavior).
- **Slot-1**: new version loads on next Chrome start (watchdog restart /
  session switch / container recreate) — never restarted under a live
  user (spike-user2 was active).

## Known minor (accepted, not blocking)

- If an error tab is active at suspend/restart, the D5 tab snapshot may
  record the `chrome-extension://…error.html` URL and restore it after a
  relaunch (shows the last error card again). Cosmetic; same class of
  behavior as restoring any page. Revisit if it annoys in pilot.
- Renderer crashes ("Aw, Snap!") are not navigation errors —
  `onErrorOccurred` does not fire for them; out of scope (spec 17 note
  keeps the crash page bar-less; supervisord auto-restart recovers).
