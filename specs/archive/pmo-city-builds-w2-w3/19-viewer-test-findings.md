# Viewer Test-Session Findings & Fixes Needed for Optimization

> **Session:** 2026-08-17 — live test on the W1 viewer (`cloudbrowser.dev01.pmo.city`),
> CRM app `alsei-residentiel.getunlatch.com/admin/re-purchases/?mode=CRM`
> (ALSEI RESIDENTIEL re-purchase pipeline, 27,667 records).
> **Status:** findings recorded; workaround live; proper fixes scheduled W2/W4.
> These are the accumulated problems to solve when optimizing the whole system —
> do not lose them in W2 planning.
>
> **W2 (2026-08-17) — fixes applied & verified on the live viewer (D4/D6/D7/D12):**
> - **F-1/F-2 FIXED + D7 CLOSED 2026-08-25 (spec 71)**: Chrome launches `--kiosk --disable-infobars`
>   (prepare-chrome.sh) — no tabs/toolbar AND the CfT notice is gone. The
>   montigaud live re-check used his own usable GrantHub grant to enter the
>   CRM and proved the footer fully visible at native 100% zoom: viewport
>   1280×720; footer rect y=672..720; `Lignes par page : 25`,
>   `1 - 25 sur 27678`; five nearby pagination controls. No F11 or zoom
>   workaround is required.
> - **F-4 FIXED (both flakes)**: browser-use 0.13.8 re-validated on the live
>   viewer (`d6-revalidation.py`): tab switch works via
>   `get_or_create_cdp_session(target, focus=True)` — W1 -32001 gone;
>   downloads land in /data/downloads once
>   `Browser.setDownloadBehavior(allow, /data/downloads, eventsEnabled)` is
>   set at connect — browser-use does NOT set it on external browsers (W1
>   downloads silently went to ~/Downloads). `downloaded_files` list stays
>   empty for external browsers (informational only; retrieval reads the
>   per-user area).
> - **F-5/F-6 FIXED**: `TranslateEnabled=false` policy (translate-policy.json)
>   + `translate.enabled` pref; popup janitor in window-manager.py (extension
>   popups never pinned fullscreen, closed after 60 s; service workers
>   untouched — page-only logic verified live).
> - **New (D4)**: restart-api on :9230 — `POST /restart` + CDP watchdog
>   (self-heal verified: `kill -9` chrome → auto-restart in < ~2 min).

---

## F-1 — Viewer canvas fit: Chrome UI chrome eats the 1080 px canvas ⚠️ CRITICAL

**Symptom (user report):** "The Chrome window is spanning under the neko window.
We cannot access pagination." Table rows visible to the bottom edge, no
pagination bar anywhere.

**Root cause:** the Xvfb canvas is 1920×1080 and the Chrome window is pinned to
1919×1079 (window-manager), but Chrome's own UI chrome sits on top of the page:
tab bar ≈ 40 px + toolbar ≈ 41 px + "Chrome for Testing" notice ≈ 52 px
= **≈ 141 px**. The page's visible area is therefore only ≈ 939 px tall. The CRM
dashboard is a *fixed-height* layout (body `scrollHeight` = 1080 = viewport —
the page itself never scrolls), and its table footer / pagination sits at
page-y ≈ 1040–1072 → on screen that is y ≈ 1181–1213, **below the visible
1080 px** → unreachable. The page cannot scroll, so there is no way to reach it.

**Evidence chain (why two views disagreed):** CDP `Page.captureScreenshot`
renders the page viewport **without** Chrome UI chrome → DOM + page-capture said
`pagination visible: true` (y 1040–1072). The raw X screen (what the user sees)
showed table rows to the very bottom edge and no pagination. Ground truth is
the X screen.

**Workaround (live, reversible):**
1. **F11 fullscreen** — removes tabs + toolbar (−89 px).
2. **90 % zoom** (one `Ctrl+−`) — compensates the 52 px CfT notice.
→ pagination now at screen-y ≈ 989, fully visible & clickable (verified on
screen: "1 - 25 sur 27667", prev arrow disabled, next arrow active, last row
fully visible). `Ctrl+0` resets zoom; zoom is per-site persisted.

**Fixes needed for optimization (W2/W4):**
- Launch Chrome in **kiosk mode** (`--kiosk` in chrome.conf) — no tabs/toolbar
  at boot; verify the CfT notice is also hidden in kiosk (to-verify).
- Suppress the CfT notice: **no dismiss button exists** (see F-2) → custom image
  or enterprise policy research.
- Alternative considered: raise Xvfb resolution (e.g. NEKO_SCREEN 2560×1440) —
  does not fix the ratio (chrome eats fixed px); zoom-out is more robust.
- **Acceptance rule for W2:** "footer / pagination visible without scrolling
  hacks" on every app tested (CRM, Vaultwarden web, docs, …).

**Measured geometry (CRM, 1920×1080, pre-fix):**
table wrapper `.v-table__wrapper` rect [64, 176, 1840, 856]; clientH 844;
scrollH 937; scrollTop 93; pagination "1 - 25 sur 27667" [1726, 1040, 1904, 1072];
`window.innerHeight` = 1080; body scrollHeight = 1080 (no page scroll).

---

## F-2 — "Chrome for Testing" notice bar has NO dismiss button

**Verified pixel-by-pixel** (CfT 128.0.6613.137): dark bar y 0–52, full width;
only a "Download Chrome" link at x 1773–1904; **no close/X/× control anywhere**
(left, middle, or right of the link). The 52 px cannot be reclaimed
interactively.

**Fix needed:** kiosk mode / custom image / policy. Also worth testing whether
the notice disappears when launched via `--kiosk` or with
`--disable-component-update`-style flags. Permanent fix belongs to the W2/W4
tooling image work.

---

## F-3 — Measurement trap: CDP page-capture ≠ X screen (what the user sees)

CDP `Page.captureScreenshot` renders the page without Chrome UI chrome;
`getBoundingClientRect` reports layout positions even for clipped content.
Either alone can wrongly prove "pagination is visible".

**Method (keep for all future geometry debugging):** synchronous dual capture —
raw X screen (`scrot` inside the viewer) + DOM rects at the **same instant**;
compare screen coordinates with `rect + chrome_offset`.

**Screen-capture plumbing (scp trap):** the file lives **inside the container**
(`docker exec … scrot /tmp/screen.png`) — plain `scp` from the host fails with
"No such file". Stream it: `ssh host 'docker exec -i <viewer> cat /tmp/screen.png'
> local.png`.

---

## F-4 — browser-use tab switch flaked live (agent automation layer)

Test-session evidence, on the real viewer endpoint:
- Playwright `connect_over_cdp` **stalls fetching the WS URL** from
  `/json/list` → 15 s TimeoutError (raw WS handshake works: HTTP/1.1 101).
- browser-use 0.13.8 **connects**, then the session manager flakes on tab
  operations: "Session with given id not found" (-32001), "Initialization
  timeout after 2.0s: 3/5 sessions ready", viewport errors; `.switch_to_tab`
  attribute does **not** exist in this version → crash; WS handler exited /
  reconnected.
- **Working path = minimal raw-CDP client** (websockets 15.0.1):
  `GET /json/version` → `webSocketDebuggerUrl` → `Target.attachToTarget`
  (targetId, `flatten: true`) → Runtime/Page/Input commands. Full round trip
  (screenshot + DOM extract) ≈ 25 s.

**Fix needed (W2):** re-validate browser-use on tab switch / downloads; keep the
raw-CDP client as the fallback (it is the deterministic path and the broker
pattern already uses CDP). This is why W2 re-validation exists — the product
decision (browser-use as token-efficient layer) stands, but tab switching is
the weak spot to fix or work around.

---

## F-5 — Google Translate popup auto-appears (viewer profile hygiene)

A Google Translate popup opened over the top-right area of the CRM page
(x ≈ 1328–1708, y ≈ 81–128) — auto-translate offer for a non-browser-language
page. Overlays content; can hide controls.

**Fix needed (W2):** disable auto-translate in the viewer profile
(`Preferences` translate settings / policy `TranslateEnabled: false`), remove
unneeded language packs from the custom image.

---

## F-6 — Bitwarden popup windows persist at (0,0) 480×630 (watch-out)

`xdotool search --onlyvisible` lists **two** Bitwarden popup windows (ids
12582938 / 12582941) at Position 0,0, Geometry 480×630 each. They did **not**
appear in any X-screen capture during the session (not visually confirmed), but
two stale popup windows parked at top-left is a risk: when a popup opens it can
overlay the top-left of the app (and 480×630 × 2 overlap the first rows).

**Fix needed (W2):** window-manager / janitor should close stale extension
popup windows (they are never useful parked), or verify they stay unmapped.

---

## F-7 — Fullscreen (F11) vs window-manager pin: compatible (verified)

The window-manager pins the Chrome window to 1919×1079 on an interval; Chrome
browser-fullscreen (F11, no WM needed) kept geometry at 1919×1079 and rendered
fullscreen correctly — the pin did **not** fight the fullscreen state.

**Fix needed (W2):** re-verify against kiosk mode (`--kiosk`) once implemented
(kiosk is a window state; the pin sets geometry — likely fine, verify anyway).

---

## F-8 — CRM app layout (informs CRMOC pilot)

- Fixed-height dashboard: body `scrollHeight` = 1080 = viewport → **no page
  scroll**; every overflow is an inner scroller.
- Table wrapper: visible 1828×844 (clientH 844, scrollH **937**) → the last
  ~93 px of the table (and its footer) only appear after scrolling the inner
  scroller; horizontal content **7944 px** wide → inner horizontal scroll too.
- Data table 27,667 records / 25 per page; pagination is the bottom-right
  footer, NOT part of the inner scroll — it is positioned below the wrapper and
  was the element pushed off-screen by F-1.
- Takeaway: apps with fixed-height dashboards are the worst case for the
  canvas-fit problem; the kiosk fix (F-1) is mandatory before the CRMOC pilot.

---

## Test-session results (what worked — keep)

- **Agent reads the screen: ✅ GREEN.** Full raw-CDP round trip
  agent → pmoc-lan → CDP relay (10.0.37.9:9223) → Chrome: attach, screenshot,
  DOM extraction, data-structure summary delivered (49-column table, 7-stage
  funnel 6832→2123→37→1→1→1→18672, related entities promoteur/programme/
  contact/vendeur/activités/tâches/lookups, open modals OTP/recommandé/notif).
- CDP endpoint: **must use the resolved IP** `10.0.37.9:9223`, not the
  hostname (`viewer-4guplgcrvug7l7h64m2cxkm1` → 63-byte HTML error; Chrome
  ≥119 Host-header gotcha, re-confirmed live).
- Screen read + geometry debug ≈ 25 s round trip — acceptable for agent assist.

---

## Fix list (roll-up — feed W2/W4 planning)

| # | Finding | Fix | Phase |
|---|---|---|---|
| F-1 | Chrome UI chrome (≈141 px) eats canvas → footers below fold | kiosk-mode launch; verify CfT notice hidden; footer-visibility acceptance rule | W2 |
| F-2 | CfT notice bar, no dismiss button (52 px stuck) | kiosk / custom image / policy research | W2/W4 |
| F-3 | CDP capture ≠ X screen (measurement trap) | synchronous dual-capture method (this doc) | — (method) |
| F-4 | browser-use tab switch flaky (-32001, no `.switch_to_tab`) | re-validate W2; raw-CDP fallback kept | W2 |
| F-5 | Google Translate popup auto-opens | disable translate in profile / policy | W2 |
| F-6 | Bitwarden popup windows parked at (0,0) | janitor closes stale extension popups | W2 |
| F-7 | Fullscreen vs window-manager pin | verified compatible; re-check with kiosk | W2 |
| F-8 | Fixed-height dashboards = worst canvas-fit case | kiosk fix mandatory pre-CRMOC pilot | W2 |
