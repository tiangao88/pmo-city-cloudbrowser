# Spec 31 — Results & live verification (2026-08-21)

> Evidence log for `31-queue-and-session-limits.md` §13 (implementation plan).
> All live checks against `cb-fleet-v2` on mother01 (dev cloudbrowser service,
> uuid `okixw2fxnwn1lakxvxajodww`). Router: `10.0.34.2:8081`.

## 1. Local harness — 14/14 ✅

`scripts/test-router31.py` (fake slots on 19081/9230 via
`router31-bootstrap.py` getaddrinfo monkeypatch → 127.0.0.1):

- Landing: free slot → "Open Browser" (`?pwd=&usr=`); busy → queue redirect
- Queue: position/ETA/waiting list; ETA cold start `tier max ÷ 2`; adaptive
  median after completed sessions
- Expiry reaper: suspend → archive `reason=expired` → next offer → re-queue
- Agent API: POST/GET/DELETE, 202 semantics, instant-grant fast path,
  501 when `CB_AGENT_TOKEN` unset
- Admin jump-ahead (`CB_ADMIN_EMAILS`), boot hygiene (stale stickiness purge)
- **Regression (added with the 6a fixes): release drops queue entry**

Commit `8f97113` (router v3, harness, bootstrap, compose) + fix commit
(6a) — pushed.

## 2. Deploy — compose PATCH ✅

`coolify-local.sh PATCH /api/v1/services/okixw2fxnwn1lakxvxajodww`
with base64-only `docker_compose_raw` (staged `/tmp/patch-compose.json`):

- Response: `{"uuid":"okixw2fxnwn1lakxvxajodww","domains":[...]}`
- Compose re-read: `CB_HUMAN_SLOTS` ✅, `NEKO_PASSWORD` ✅,
  `CB_QUEUE_POLL_INTERVAL_S` ✅ (6,109 bytes)

## 3. Scripts volume seed ✅

`router-v2.py` + `restart-api.py` copied into
`okixw2fxnwn1lakxvxajodww_scripts` volume (root:root 644) via throwaway
`alpine:3.20` container; mounted at `/app`. **Final deployed hashes**
(after the 6a fixes re-seed; verified sha256 volume == repo == container):

```
repo/vol/container  router-v2.py   sha256 24d24f522c4f178434da7543ee2d63bb41f58139e3a8f55f0248ede75f62c3de
repo/vol/container  restart-api.py sha256 e2222649eac0478439f3ed2e7cc2acf2d91501464d316c13efc7103cbbdb19fe
```

## 4. Service restart ✅

`POST /api/v1/services/{uuid}/restart` → "Service restarting request queued".
After ~60 s: **5/5 containers `Up (healthy)`** — router, slot-1, slot-2,
janitor, clamav.

Router boot log:

```
[router] v3 spec31: human_slots=1 agent_slots=0 human_max=5.0m agent_max=240.0m admin=[] agent_token=unset
[router] v3 on :8081, N_SLOTS=2 auto_create=True state=/data/state/router-state.json sweep=30.0s reaper=10.0s
```

Container env: `CB_HUMAN_SLOTS=1`, `CB_AGENT_SLOTS=0`,
`CB_HUMAN_MAX_SESSION_MIN=5`, `NEKO_PASSWORD` set.

## 5. Live smoke (spec 31 §10 scenario, part 1) ✅

Simulated SSO users via `Remote-Email` header (host header
`cloudbrowser.dev01.pmo.city`):

| Check | Result |
|---|---|
| A (`spike-user@aikumi.pro`) GET `/` | `<title>Cloudbrowser</title>` + **"Open Browser"** button, `href="/?pwd=neko&usr=spike-user%40aikumi.pro"` — auto-login link, neko login form never rendered |
| B (`montigaud@aikumi.pro`) GET `/` | `<title>Cloudbrowser — queue</title>` + "Your position" |
| B `GET /queue/status` | `{"status":"waiting","position":1,"eta_s":150,"waiting_humans":["montigaud@aikumi.pro"],"agent_count":0,"queue_id":"q-1"}` |
| `GET /fleet/status` | `users:["spike-user@aikumi.pro"]`, `slots:{"1":"spike-user@aikumi.pro"}`, `queueDepth:{"human":1,"agent":0}` |

## 6. Live expiry (spec 31 §10 scenario, part 2) ✅

Clean state, fresh users (`a2@aikumi.pro` = A, `b2@aikumi.pro` = B),
`CB_HUMAN_MAX_SESSION_MIN=5`, CDP activity pump on slot-1 (defeats the
slot-level 2-min idle reaper so the **router's max-duration** reaper is the
one that fires):

| Check | Expected | Observed |
|---|---|---|
| A lands | slot 1 + Open Browser (fresh user, no archive) | ✅ `<title>Cloudbrowser</title>` + "Open Browser" |
| B lands | queue page, position 1 | ✅ "Your position", `eta_s: 150` |
| T+6m40s fleet/status | A archived `expired`, B offered | ✅ `users:[b2]`, `slots:{1:b2}`, `archives:{a2:"expired"}`, B queue entry `active` slot 1 |
| A re-lands | **queue page** (never neko login) | ✅ `<title>Cloudbrowser — queue</title>` + "Your position" |
| B queue/status | `active` + `open_url` | ✅ `{"status":"active","open_url":"/?pwd=neko&usr=b2%40aikumi.pro"}` |
| B opens URL (wake on **suspended** slot) | session up, no 500 | ✅ `<title>Cloudbrowser: b2@aikumi.pro</title>` |

## 6a. Defects found live during acceptance + fixes (2026-08-21)

The first two live attempts exposed two defects (both masked in the local
harness: fake slots always accept `/wake`):

1. **Slot `/wake` 500 for users without an archive** (`restart-api.py`
   `do_wake` → `restore_user` → "no archive" → `{"ok": False}` → 500).
   Consequence: a **fresh user could never take a suspended slot** — the
   router's offer→wake→release loop spun forever (`wake slot-1 failed:
   HTTP Error 500` ×N, entry reset to waiting every reaper tick).
   **Fix**: no archive → plain fresh wake on an empty profile
   (`wipe_slot_dirs()` extracted from `restore_user`; wipe → set user →
   start chrome/title-proxy → restore_tabs opens homepage). Live-verified
   by A2 (fresh) and B2 (wake on suspended slot).
2. **Stale "active" queue entries survived release** (`router-v2.py`
   `_release` cleared users/slots/sessions but never the queue entry).
   Consequence: released users' entries lingered as `active` with a stale
   slot, polluting `queueDepth`/`/queue/status` semantics (observed live:
   q-1 montigaud `active` long after its session was archived idle).
   **Fixes**: (a) `_release` now drops the user's queue entry; (b) boot
   hygiene drops stale `active`/`offered` entries whose user is gone
   (live: `[router] boot: dropped stale queue entry q-1
   (montigaud@aikumi.pro, active)`); (c) `/fleet/status` now exposes the
   sanitized `queue` list (ops visibility).

Regression: harness extended with "release drops queue entry" →
**14/14 pass** (was 13/13). Deployed (scripts volume re-seeded,
sha256 `24d24f52…` router / `e2222649…` restart-api, service restarted
5/5 healthy), full live scenario re-run ✅.

## 6b. Defect: idle-suspend leaves the tab on the neko LOG IN (2026-08-21, Tigo)

Tigo: "After the session expired I still get this page [neko LOG IN].
I should be on the queue page instead."

**Root cause (test-value timeouts + a UX gap):**
1. The live fleet still ran fast-test parameters: `IDLE_TIMEOUT_MIN=2`,
   `IDLE_GRACE_MIN=1` (slot-level) and `CB_HUMAN_MAX_SESSION_MIN=5`
   (router-level; spec 31 §4 marks it "test value; prod later"). Tigo's
   session was **idle-suspended at 2 min** (not max-duration-expired), so
   his archive reason was `idle` (resumable), not `expired` (re-queue).
2. Idle suspend stops **title-proxy** to drop the session's WebSocket
   (`restart-api.py do_suspend`), so the already-open neko SPA reverted to
   its built-in LOG IN screen. The router is only involved on the *next*
   page load — nothing redirected the dead tab back to the queue/landing
   page. The "never show the neko login" guarantee (spec 31 §9) only
   covered the entry flow, not in-flight sessions.

**Fixes (2026-08-21):**
1. **Production values** (Coolify envs, applied on deploy):
   `IDLE_TIMEOUT_MIN` 2→20, `IDLE_GRACE_MIN` 1→5,
   `CB_HUMAN_MAX_SESSION_MIN` 5→30. A human reading a page no longer gets
   suspended mid-work by the 2-min test timeout.
2. **Router session watchdog** (`router-v2.py`):
   - new read-only endpoint `/fleet/my-status` → `{email, state:
     active|queued|idle|expired|new}`. Query-only — never transitions
     state (unlike `/queue/status`, which assigns/wakes/enqueues and
     would auto-wake a dead tab's slot).
   - the human entry flow (`/?pwd=…&usr=…` — the Open Browser click) now
     serves the slot's neko index with a small watchdog injected that
     polls `/fleet/my-status` every 5 s and, the moment the state is not
     `active`, redirects the tab to the router root — which then serves
     the landing page (idle → resume) or the queue page (expired →
     re-queue). The neko LOG IN can no longer take over an in-flight
     session.

Harness extended +3 (my-status active / pwd-root watchdog injected /
my-status expired after max-duration) → **17/17 pass** (was 14/14).
Deployed (router re-seeded sha256 `f84cf1fe67…`, service restarted 5/5
healthy). Live probes: `/fleet/my-status` for montigaud's archive →
`{"state": "idle"}`; `/?pwd=…` response contains the injected watchdog.

## 7. Test hygiene

- All test sessions released (`/fleet/release`, `reason=idle`) — no leftover
  slot ownership.
- Router state file reset once between smoke and expiry legs (stale
  queue-entry from the first smoke test would otherwise archive-wake B).

## 8. Known gaps (by design this iteration)

- **Agent-slot path not live-tested**: `CB_AGENT_SLOTS=0` (human path
  first, spec 31 §10). Harness covers agent API + fast path.
- **Browser-level auto-login**: URL/param mechanics verified (button href,
  neko 2.9.0 `connect.vue` + WS `?password=` code review). End-to-end
  human click-through to a live session remains for a real SSO user
  (Tigo) — router-side behavior is fully covered above.
- **ETA median** needs a few completed sessions to warm up (cold start
  fallback until then).

## 9. Spec 31 follow-up (2026-08-22): self-heal force-release — 22/22

Regression added: a slot whose `/suspend` succeeds but whose release
callback never lands (stuck `_suspended` latch) must not wedge the fleet.
Router now force-releases the expiring user after `grace = max(2×reaper
interval, 10s)` and advances the queue. Also fixed in the same pass:

- `_eta_for` crash when `_enqueue_human` returns an entry id (string)
  instead of a dict (was 500 on the queue page for a non-queued user).
- Queue page: brand `<a class="neko">` no longer links to the neko GitHub
  repo (matches session header); brand span gets the Whitney font family.
- title-proxy (session header): removed neko's `fa-file` admin toggle
  (burger + mouse + locks already removed) and neutralized the `a.neko`
  GitHub link in the rendered client — session top bar now matches the
  queue page (brand · Secrets · CloudFiles · email).

Harness **22/22 pass** (was 21/22; the failing self-heal assertion was a
broken test poll — it treated the queue-waiting state as "released" — not
a router defect; reaper was verified alive throughout via stack dumps).
Deployed to fleet: router re-seeded sha256 `272271b42f…` (backup
`router-v2.py.bak-20260822`), title-proxy redeployed on both slots,
router + title-proxy restarted. Live probes: `/fleet/status` healthy,
queue page brand link has no href, font-family:Whitney present, session
header render shows only Secrets + CloudFiles pills.

## 10. Queue page layout (2026-08-22, Tigo review)

Queue card now shows, below the position/ETA block:

    Active session: tigo-test@x.pro
    ────────────────────────────────
    1. montigaud@aikumi.pro
    2. spike-user@aikumi.pro

- The viewer's own email IS in the numbered list (previously top-right
  only). Other users' emails remain gated by CB_QUEUE_SHOW_EMAILS.
- `/queue/status` now returns `waiting: [{email, pos}]` in true queue
  order (priority desc, enqueued_at asc) replacing `waiting_humans`.
- List is centered in the card; teal position numbers (`.qn`); explicit
  `<hr class="sep">` between the Active session line and the numbered
  list.
- Harness updated (own-email-in-list assertion), 22/22. Deployed
  (router sha256 `4549ac918a…`), live payload verified for montigaud:
  `waiting: [montigaud pos 1, spike-user pos 2]`, `active_humans:
  [tigo-test@x.pro]`.

## 11. Landing page top bar (2026-08-22, Tigo review)

The "session ready" landing page (`_landing_page`) was missing the
CloudBrowser top bar — it rendered only the centered card. Fixed:

- Body switches to flex-column; the neko-style `.header` (40px,
  #202225) with PMO logo + CloudBrowser wordmark (bold C + B) sits on
  top; card centers in the remaining space (`margin:auto`).
- Right side carries the same shortcuts as the queue page: 🔒 Secrets
  (SECRETS_URL), 📁 CloudFiles (FILES_URL), logged-in email top-right.
- `<title>` fixed "Cloudbrowser" → "CloudBrowser"; card h1 also bold
  C+B (brand rule).
- Harness 22/22; deployed (router sha256 `…`, volume copy
  router-v2.py.bak-landingbar); live-verified via Host+Remote-Email
  probe on mother01.

## 12. Unified top bar — spec 37 (2026-08-22, Tigo go)

Implemented across all surfaces (design LOCKED in `37-topbar-design.md`):

- Right side order everywhere: `CloudFiles ⏐ Secrets·Shared ⏐ email`.
  Secrets+Shared are ONE block (no separator between them); separators
  only between CloudFiles/Secrets and Shared/email (1px `rgba(255,255,255,.15)`).
- **Shared pill (new):** 🔗 green "Shared" / red "Not Shared" from GrantHub
  state. `GRANTHUB_URL` (default `https://cloudbrowser.dev01.pmo.city/connect`)
  is the navigation target; optional `GRANTHUB_STATUS_URL` JSON endpoint
  `{"shared": bool}` keyed by `Remote-Email` — unset/unreachable → "Not
  Shared" (never a false green). Same hook in router, title-proxy,
  downloads-api.
- Surfaces: landing + queue (router `_top_bar`), session header
  (title-proxy injection, prepend-in-reverse ⇒ DOM order files·sep·secrets·
  shared·sep·email), CloudFiles (downloads-api: wordmark/title "CloudFiles",
  right side CloudBrowser ⏐ Secrets·Shared ⏐ email).
- Titles normalized: "CloudBrowser"/"CloudBrowser: {email}" everywhere on
  browser surfaces; "CloudFiles"/"CloudFiles: {email}" on files.
- CloudFiles queue: **none** (Tigo confirmed) — always accessible.
- Harness 22/22; downloads-api render smoke (pills order + 2 seps) green.

## 13. Script rename (2026-08-22, Tigo)

Clean names, version suffixes dropped:
`router-v2.py` → `router.py` · `test-router31.py` → `test-router.py` ·
`router31-bootstrap.py` → `router-bootstrap.py`. Compose command updated to
`python /app/router.py`; stale `/opt/data/router-v2-live.py` deleted; volume
`router-v2.py` + `.bak-*` files removed after verified deploy.

### 12b. CloudFiles no-queue routing (spec 37 §2.5 — fix)

Live probe during deploy showed the cloudfiles host falling through to the
generic branch: it ACQUIRED a slot and enqueued → queue page. Violated the
locked "no queue on CloudFiles". Fixed in `router.py` with a dedicated
`cloudfiles` branch (no `_resolve()`, no `_enqueue_human()`): route to the
user's assigned slot if any (their downloads live there), else the human
slot (1); 502 if that slot's downloads-api is down. Harness: 2 new tests
(proxied to slot surface + visitor NOT enqueued) → 25/25. Live: cloudfiles
host now returns the CloudFiles page.
Caveat (D8/W3, unchanged): downloads volumes are per-slot, so an idle user
with no assigned slot may see another slot's file list.

## 14. Incident: "PLEASE LOG IN" instead of queue page (2026-08-22, Tigo)

Symptom: spike-user@aikumi.pro saw the **neko login panel** (clean URL, our
top bar present) instead of the queue page.

Evidence (router logs + state): the router served the **landing page ×4**
(persisted active assignment survived the 09:57 redeploy), then the reaper
EXPIRED the session, then fresh visits → queue page ×3 (correct). The
screenshot was an **in-flight session tab**: the slot WS dropped and neko
shows its login screen instantly.

Root cause chain:
1. **Stale session clock.** `sessions[email].started_at` persists in
   router-state.json. After a redeploy it carried the PRE-deploy start time;
   re-entering a session via the landing page never refreshed it → the
   reaper expired a fresh, actively-used session within minutes of boot.
2. **Grace-window blind spot.** While the reaper tears a slot down
   (suspend → release, ~10s grace), `/fleet/my-status` still returned
   "active" → the watchdog could not bounce the tab → neko's login screen
   stayed visible for the whole grace + poll interval.

Fixes (all in router.py):
- Browser entry (`/?pwd=…&usr=…`) now refreshes `started_at` and persists
  it — no stale-clock expiry, even across future redeploys.
- `/fleet/my-status` returns `expired` during the grace window (user still
  assigned but being torn down) → watchdog bounces immediately.
- `GET /` (cloudbrowser root) during the grace window serves the queue
  page, not the landing page — no re-entry race.
- Watchdog poll 5s → 2s (login-screen flash at worst a couple of seconds,
  and only on genuine end-of-session expiry).

Harness 28/28 (3 new tests: re-entry refreshes started_at; my-status=expired
while assigned during grace; GET / = queue page during grace). Deployed +
live-verified: spike-user now gets the queue page, my-status=queued,
watchdog MS=2000.

## 15. Session top bar: missing email + "Cloudbrowser" wordmark (2026-08-22, Tigo)

Symptom (Tigo screenshot, live session): the neko session header showed the
spec-37 pills (CloudFiles · Secrets · Not Shared) but NO dynamic email at
the right, and the wordmark read "Cloudbrowser" (lowercase b) instead of
CloudBrowser (bold C+B).

Root causes (two independent):
1. **Email never reached title-proxy.** The router's Open-Browser entry
   (/?pwd=…&usr=…, router.py) fetches the slot index itself to inject the
   watchdog — but the fetch carried NO Remote-Email header. title-proxy
   therefore saw an empty email: no email `<li>`, and `<title>` fell back
   to "CloudBrowser" without the email.
2. **Bundle wordmark is `loudbrowser`.** neko's brand renders
   `<span><b>C</b>loudbrowser</span>` (patched bundle: 4× "loudbrowser").
   title-proxy's injection removed the chrome but never rewrote the
   wordmark text.

Fixes:
- router.py `pwd=` branch now forwards `Remote-Email: <email>` on the slot
  index fetch → title-proxy renders the email + "CloudBrowser: <email>".
- title-proxy injection: rewrites `loudbrowser` → `loud<b>B</browser>` in
  `a.neko span` (applied in `ap()` so Vue re-renders re-fix it) and injects
  `a.neko span b{font-weight:900}` (matches queue-page brand styling).
- title-proxy `_user_email()` helper: falls back to the `usr=` query param
  (the Open Browser href) when Remote-Email is absent (direct-slot access).

Harness 29/29 (new test: pwd-root forwards Remote-Email to the slot).
Verified: curl on the exact user path (title + E= + wordmark + style) and a
headless-Chromium render of the real page — menu = CloudFiles | Secrets·
Shared | email, brand = CloudBrowser bold C+B, title = "CloudBrowser: …".

## 16. CloudFiles top bar: restyled to match the neko toolbar (2026-08-22, Tigo)

Symptom (Tigo screenshot, live CloudFiles page): the CloudFiles top bar
looked different from the queue/landing bar and the session header — flat
50px bar in the page background (#12141a) with a small 15px system-ui
wordmark, instead of the neko-style header.

Root cause: downloads-api.py's PAGE template used its own bar styling
(50px, #12141a, border-bottom, 15px/600 system-ui brand) while the other
surfaces mirror the neko header (40px, #202225, 30px Whitney brand with
`b{font-weight:900}`). Pill/sep/email styles already matched.

Fix (downloads-api.py):
- .cb-bar → height 40px, background #202225, border-bottom removed
- .cb-word → 30px/line-height 30px, font-family Whitney, color #dcddde,
  `b{font-weight:900}` (bold C+F)
- .cb-logo → 30px (matches the neko brand image height)
- th sticky offset 50px → 40px (bar height)

Deployed to both slots (scripts volume, supervisorctl restart
downloads-api). Verified: computed styles on the live page (bar 40px /
rgb(32,34,37), brand 30px Whitney, logo 30px) + headless-Chromium
screenshot of the rendered bar — consistent Discord-style header matching
the other surfaces.

## 17. Queue page ETA frozen at 26 min (2026-08-22, Tigo)

Symptom: reloading the queue page always showed ≈26 min wait — the ETA
never decreased. Tigo expected the remaining time to count down.

Root cause: _eta_for computed a STATIC statistical estimate
`(pos/coming) × median(history)` — no `now` term at all. The value only
changed when queue composition/history changed, never with wall-clock
time. (The page itself already auto-polls every CB_QUEUE_POLL_INTERVAL_S
= 5s; it was re-rendering the same constant.)

Fix (_eta_for rewrite, time-based pipeline model):
- Each active session of the tier contributes its REMAINING time
  (started_at + MAX_SESSION_S − now) to a sorted list — the slot-free
  pipeline.
- Position p ≤ busy → ETA = p-th smallest remaining (the slot that will
  serve you frees at that time).
- Position p > busy → all busy slots free once, then the queue drains in
  `med` steps (each new occupant runs ~median duration): `divmod` over the
  per-slot streams (r_j + i·med).
- Expiring sessions (reaper grace, max(2·CB_REAPER_INTERVAL_S, 10s)) keep
  ETA ≥ grace-remaining instead of hitting 0 early.
- Floor stays CB_QUEUE_POLL_INTERVAL_S.

Harness 30/30 (new test: poll /queue/status twice 2s apart → eta strictly
decreasing). Live-verified on the fleet: montigaud (pos 1, waiting) saw
eta_s 1200 → 1170 over 30s — counts down with the active session.
## 18. Favicon = PMO City logo + tab title convention (2026-08-22, Tigo)

Tigo (screenshots + 3 asks): (1) "space missing between the logo and the
text" in the tab pill — the tab showed Chrome's DEFAULT BLUE GLOBE because
the queue page had no favicon at all; (2) the queue tab title should read
"CloudBrowser" not "CloudBrowser — queue"; (3) "for all pages the favicon
should be the PMO City logo and not the Neko cat".

Analysis: the tab pill in the screenshots is Chrome's NATIVE tab UI inside
the embedded browser (side panel "Incognito Tabs" — confirmed not ours: the
tab-bar extension (content.js, md5-identical on slot and staging) has no
such strings, and the neko client bundle renders no browser tabs). The
native pill's icon comes from the PAGE favicon — which the queue page did
not declare → default globe. The icon↔text gap in the native pill is
Chrome's own layout (not injectable); the visible "missing space" was the
absence of any branded icon. On our own tab bar (content.js), the same
favicon→title spacing was tightened with margin-right:6px.

Fixes (all four surfaces, single brand mark):
- PMO City logo SVG (traced from https://pmo.city/ navbar: teal disc
  #3D6475, mint inner disc #6DD5B5, flat bar) inlined as a base64 data URI.
- router.py (queue + landing pages): <title>CloudBrowser: <email></title>
  + rel="icon" link with the data URI. Queue title was "CloudBrowser —
  queue".
- title-proxy.py (session page): neko's 4 icon links (icon/16, icon/32,
  apple-touch, mask) → single PMO City data-URI link. Pitfall hit live:
  ICON_RE must be a BYTES pattern (rb'...') — the page body is bytes at
  that point; a str pattern raises TypeError and 502s the session page
  (caught by curl probe post-deploy, fixed, re-pushed).
- downloads-api.py (CloudFiles): same rel="icon" link.
- content.js tab bar: .tab img gains margin-right:6px.

Verification: harness 32/32 (new: landing + queue title/favicon asserts;
the spec-37 top-bar order check now keys on cb-email-li — the email moved
earlier in the body once it appears in <title>). Live: queue page title
"CloudBrowser: montigaud@aikumi.pro" + PMO favicon; session page (both
slots) exactly ONE PMO favicon link + email title; CloudFiles page PMO
favicon. Harness port collision pitfall: the probe SSH tunnel (-L
18081:slot:8081) must be down before running test-router.py — it steals
the harness router port and every check hits the live slot.
## 19. Queue ids collide after restart — two users shown at position 1 (2026-08-22, Tigo)

Symptom (Tigo screenshot): the queue page listed montigaud@aikumi.pro AND
spike-user2@aikumi.pro BOTH at "position 1" (spike-user2 should be 2).

Root cause: queue entry ids come from an in-memory counter (QUEUE_ID) that
resets to 1 on every router restart. The queue itself is PERSISTED
(router-state.json), so a fresh entry could reuse the id of an entry that
survived a restart. Live state confirmed the collision:
  q-1 spike-user@aikumi.pro  (active)
  q-1 montigaud@aikumi.pro   (waiting)   ← same id!
  q-1 spike-user2@aikumi.pro (waiting)   ← same id!
_eta_for resolves position by `e["id"] == entry["id"]` (first match in
sorted order) → both waiting users matched montigaud's entry → both got
pos 1. The id collision also endangered DELETE /queue (by id) and agent
polling (wrong entry).

Fix:
- `_next_eid()` replaces the in-memory counter: the sequence is stored in
  the persisted state as `queue_seq`, bumped under _lock at every enqueue
  (human + agent paths) and persisted by the caller's save_state.
- Boot hygiene in load_state(): if duplicate ids are detected, renumber
  the queue by enqueue order (q-1..q-N) and set queue_seq = max(seq, N);
  when ids are already unique, queue_seq is advanced past the largest
  existing id so a restart can never reuse one.

Verification: harness 35/35 (+3 regressions: unique ids after boot,
second user gets pos 2 on the exact legacy state, fresh enqueue after
restart gets a non-colliding id). Deployed (volume push + router restart;
state survives restarts) and live-verified:
  queue ids: q-1 spike-user (active), q-2 montigaud, q-3 spike-user2
  spike-user2 /queue/status → position 2, waiting [montigaud 1, spike-user2 2]
The queue page self-corrects on its next 5s poll — no refresh needed.
## 20. Active reload lands on landing/queue + queued ETA resets on take-over (2026-08-22, Tigo)

Tigo scenario (screenshots + 4 steps): (1) spike-user has the active
session; (2) the 2 other users wait ≈29 min; (3) spike-user reloads
cloudbrowser and lands on the "Open Browser" page instead of entering the
session directly; (4) after take-over, all queued users reset to ≈30 min.

Root causes:
- (3) neko strips ?pwd/usr from the URL after auto-login, so a plain
  reload of "/" hits the router root branch, which served the LANDING page
  ("session ready / Open Browser") for any resolved slot — including an
  already-active session.
- (4) the pwd-branch refreshed started_at on EVERY entry, so each reload
  reset the active session's clock to a full 30 min → every queued user's
  time-based ETA jumped back up. (The refresh was added for the redeploy
  stale-clock case, spec 36 §14 — it over-fired on healthy sessions.)

Fixes (router.py):
- Root branch: if the email is in users BEFORE _resolve(), respond 302 →
  /?pwd=&usr= — reload enters the live session directly. Archive-wake /
  auto-create still get the landing page (wake barrier while Chrome
  comes up).
- pwd-branch: refresh started_at ONLY when stale (elapsed > tier max, or
  future timestamp / clock skew); a healthy in-flight clock is kept.
- Watchdog (injected session page): new self-heal — if the neko LOG IN
  screen (<neko-connect> element, rendered only while disconnected) is
  visible while /fleet/my-status says "active", fetch /queue/status, take
  open_url (?pwd=&usr=) and redirect. A dropped viewer WebSocket (router
  restart, title-proxy restart, blip) now repairs itself with zero user
  action. Loop guard: only redirect when the URL no longer carries pwd=
  (neko strips it after a successful auto-login).

Verification: harness 37/37 (+3: active reload → 302 with exact Location;
re-entry KEEPS healthy started_at (|Δ|<1s); skewed started_at refreshed).
Deployed (volume push + router restart; state survives). Live:
  GET / for active montigaud → 302 Location /?pwd=neko&usr=montigaud%40aikumi.pro
  session index for montigaud → watchdog contains neko-connect/loginScreen/open_url
  queue: spike-user2 pos 1 eta ≈1610s (montigaud 205s into his 30 min) — ticks down, no reset on reload

## 21. Offer grace period + zombie "Open Browser" button (2026-08-22, Tigo)

Tigo (screenshots): after spike-user's 30-min session expired he STILL saw
an "Open Browser" button on the queue page; montigaud (active) seeing it is
normal. Tigo also asked: when a user gets the option to become active, is
there a grace period before the next-in-queue gets the option? What happens
if the offered user never takes it?

Root causes:
- No real offer state existed: the reaper marked the queue head ACTIVE and
  assigned the slot + started the session clock the moment a slot freed.
  The "grace" was only the slot's 2-min idle suspend (user never attaches
  -> idle -> release -> re-offer). The session clock ran from offer time,
  not take-over, and the offer had no explicit expiry.
- Zombie button: the queue page JS revealed "Open Browser" when a poll
  returned status=active and NEVER re-hid it when the status reverted to
  waiting (release/idle/expiry) — the stale button kept its old href.

Implemented (router.py):
- NEW offer flow (CB_OFFER_GRACE_S, default 60s): when a slot frees the
  reaper OFFERS it to the queue head — entry status 'offered' with
  offer_expires_at, slot reserved in offer_holds, wake fired (chrome warm).
  The user is NOT assigned and the clock does NOT start.
- Take-over: clicking Open Browser within the grace assigns the slot and
  starts the session clock THEN (full session time; queued ETAs not
  inflated). /queue/status for an offered user returns open_url +
  offer_ttl_s; the queue page shows "Offer expires in N s".
- Grace expiry: the reaper sweeps expired offers — the user goes to the
  BACK of the queue (one-shot chance; enqueued_at=now) and is archived
  reason=offer_expired; the next tick re-offers to the new head. Restart
  mid-offer: a still-valid offer is restored (hold rebuilt); an expired
  one is swept at boot with the same policy.
- Zombie-button guard: the queue page re-hides the button (and clears the
  href) whenever a poll returns a non-openable status.
- Wake-failure on offer releases the hold and reverts the entry to waiting
  (keeps position) for the next tick.

Verification: harness 40/40 (new: B offered not active w/ ttl and no
assignment; take-over starts clock at click; post-take status active
without ttl; expired seeded offer swept to BACK with reason=offer_expired).
Deployed; live: active user -> open_url; waiting users -> no open_url, ttl
absent; queue page JS contains the zombie guard + offer countdown.

## 22. Queue page: grace/session countdown replaces the "?" (2026-08-22, Tigo)

Tigo screenshot: the queue page showed a large "?" in the "Your position"
slot together with an "Open Browser" button. His ask: instead of "?" show
the countdown of the grace period to take over the browser or lose the spot.

Root cause: the "?" was what an ACTIVE user saw — position is meaningless
once a session is live (their GET / would normally 302 into the session,
but an already-open queue page keeps polling in place and re-renders on
status transitions). The offered user's grace countdown existed only as a
small text line; the position slot always showed "?" for non-queued states.

Implemented (router.py):
- /queue/status now returns session_ttl_s (remaining session time) for
  active viewers, alongside the existing offer_ttl_s for offered ones.
- Queue page position slot becomes a live countdown (mm:ss, 1s ticker):
  - offered  -> label "Offer expires in" + grace countdown (take it or
    lose the spot — the one-shot chance from spec 36 §21)
  - active   -> label "Session ends in" + remaining session countdown
  - waiting  -> "Your position" + number (unchanged)
- The small eta line is blanked while offered/active (the big countdown
  replaces it).

Verification:
- Harness 43/43 (+2: queue page while offered carries the countdown
  wiring; active payload carries session_ttl_s > 0).
- render-offer.py: boots the router with a seeded offered entry and drives
  the page with headless Chromium — LABEL "Offer expires in", POS 0:51 ->
  0:49 (ticks down), button visible. PASS. (Screenshot /tmp/offer-countdown.png)
- Live: spike-user2 took a real offer during verification (status active,
  open_url set, session_ttl_s 1746 ≈ 29 min — take-over clock started at
  click); live queue render for a waiting user shows "Your position 1" +
  "≈ 29 min" ETA. The offer sweep was also observed live: two offer_expired
  archives, offers rotating to the oldest head.

## 23. Lapsed offer: queue page must re-render, not freeze at 0:00 (2026-08-22, Tigo)

Tigo screenshot: after his offer expired he was left on the queue page
showing "Offer expires in 0:00" with a clickable-looking Open Browser
button; he expected the page to re-render with him at the bottom of the
list.

Root cause: the queue-page poll did `clearInterval(timer)` the moment the
Open Browser button was revealed (status offered OR active — spec 37
narrowed it to active, the offer-grace work widened it back). With the
poll dead, a lapsed offer never re-rendered: label froze at "Offer
expires in", the 1 s decrementer ran the countdown to 0:00, and the
button stayed (clicking hit a dead offer). The zombie-button guard could
not help — it only runs on a poll that returns waiting, and there were no
more polls. The waiting list on the frozen page looked current only
because the viewer's position happened not to change (offer head behind
two rivals -> demoted to the back = same spot).

Fix (router.py): remove `clearInterval(timer)` entirely — the poll runs
forever. Every status change re-renders in place: offer lapse ->
"Your position" + new position + button re-hidden; session end ->
same. Cost: one tiny JSON fetch per user per poll_ms.

Verification:
- Harness 43/43 (unchanged server-side behavior).
- New render-lapse.py (headless Chromium, seeded offered entry + older
  rival + FakeSlot answering /wake): page loads showing "Offer expires
  in" + button; after the grace lapses the SAME page re-renders to
  "Your position 2", button hidden, list "1. other@x.pro / 2.
  offer@x.pro". PASS.
- Negative control: re-inserting clearInterval makes render-lapse FAIL
  with exactly Tigo's symptom (label frozen at "Offer expires in",
  POS "0:00", dead button, unchanged list).
- render-offer.py (grace countdown) still PASS; both render tests now
  use /health for the boot wait (the root 401s anonymous requests and
  the old boot poll burned the grace window in retries).
- Deployed to the fleet; in-container grep: `clearInterval(` = 0,
  zombie guard present, bare `setInterval(tick, ...)`.

## 24. Human session limit 30 -> 15 min (2026-08-22, Tigo)

Operational change: `CB_HUMAN_MAX_SESSION_MIN` 30 -> 15 (Coolify env,
router service). Redeployed the fleet; all 5 containers healthy; router
env confirmed `15`; persisted state survived (queue: spike-user waiting,
montigaud offered). Sessions started before the redeploy inherit the new
15-min ceiling on next reaper pass (started_at is preserved; elapsed
time counts against the new limit). Compose default stays
`${CB_HUMAN_MAX_SESSION_MIN:-5}`.

## 25. Phantom offer-hold strands the queue after idle release (2026-08-22, live)

Tigo: two users waited for a browser while the queue page showed an
offer countdown frozen at 0:00 with a dead-looking Open Browser button
(screenshots 1+2: different users at position 1, both frozen).

Two compounding causes:

1. STALE TABS (users): both queue pages were loaded BEFORE the §23
   poll-keeps-running fix and the 15-min session change (the pages still
   said "30 minutes"). Old JS kills the poll the moment Open Browser
   appears -> page freezes at "Offer expires in 0:00", button dead,
   countdown local-only. The fix is already deployed; a hard refresh
   (Ctrl+Shift+R) loads the new JS. Server log for >1 h: offers rotating
   every 60 s (spike-user <-> montigaud), each lapsed because nobody
   could click.

2. PHANTOM OFFER-HOLD (server, new bug): while a user was OFFERED
   (slot reserved in _offer_holds, Chrome pre-warmed) but never
   connected, the slot idle watchdog (IDLE_TIMEOUT_MIN=2) POSTed
   /fleet/release. The release handler dropped the user's queue entry
   and archived idle — but NEVER cleared _offer_holds. The reaper's
   per-slot guard (`k in _offer_holds`) then refused to offer the slot
   to the next user: montigaud stranded waiting with a free slot and no
   offer for 5+ min (verified live: state showed waiting + empty slots +
   no offer, log showed no new offers after the release).

Fix (router.py _release): clear any _offer_holds entry pointing at the
released user (loop over a copy, pop matching holds). Regression test
added to test-router.py: seed [a waiting, b waiting] -> a offered ->
POST /fleet/release {user: a} -> b must be offered within the grace
window; also asserts a archived idle + gone. Negative control (fix
reverted): b stays waiting forever, harness 46/1 FAIL on exactly the
"next user offered" check.

Verification: harness 47/47; deployed to the fleet; live state after
restart: montigaud OFFERED (log "offer montigaud@aikumi.pro -> slot-1,
grace 60s"). Users must hard-refresh their queue tabs to load the §23 JS
(the old tab keeps freezing at 0:00 forever).

## 26. ETA inflated by stale 30-min-era history + own-session double count (2026-08-22, live)

Tigo: "the 51 minute calculation here does not make sense" — queue page
showed position 2 / ≈51 min with a 15-min session limit and no active
session.

Root cause (live state + formula trace):
- med (median session duration from history) = 25.4 min: 15 recorded
  sessions, 12 of them 25-38 min from the OLD 30-min limit era (cut to
  15 min in spec 36 §24). History is never filtered by the current cap.
- busy=0 branch: `eta = (q+1)*med` with q = pos-1 → pos 2 got 2×med
  (head's session + the user's OWN future session). The ETA is a
  wait-to-OPEN, so the user's own session must not be counted.
  2 × 25.4 = 50.8 ≈ 51 min. Reproduced in harness with seeded stale
  history: 3200s ≈ 53 min.

Fix (router.py _eta_for):
1. Cap med at MAX_SESSION_S[tier] — stale history from older, higher
   limits can never inflate a step beyond today's session limit.
2. busy=0 branch: `eta = (pos - 1) * med` (slot takes the head now; the
   wait for pos is the (pos-1) occupants ahead).

Regression test: seed [a waiting, b waiting] + history [1500,1600,1700]
(25-min era) + NO active session → b at pos 2 must see eta ≈ min(med,
MAX) = 4.8s (old: 9.6s capped / 3200s uncapped). Harness 48/48;
negative control (both changes reverted) reproduces 3200s and fails the
check. Deployed; live: montigaud pos 2 → eta_s 900 (~15 min) — the
worst case = one 15-min session ahead; if the head's offer lapses the
page drops to ~1 min on the next poll.

## 27. Homepage re-added on restores — "fix once and for all" (2026-08-22, live)

Tigo: "the homepage is being opened several times… if the homepage
should be added only if there is zero tab in the session. If there is
just one tab, we should never add the home page." Live screenshot:
Yahoo + TWO home tabs, a Wikipedia tab evicted by the 3-tab limit.

Root cause chain (slot-side, restart-api.py + tabbar extension):
1. ensure_homepage() opens home at session start (zero tabs) — intended.
2. Home stays open forever and snapshot_tabs() (watchdog, every 30 s)
   persisted it INTO the snapshot (live snapshot: [aikumi.news,
   pmo.city]).
3. Every restore re-opened home FROM the snapshot — it resurrected on
   every wake/restart even when the user had real tabs.
4. MULTIPLE queued restores: do_wake spawned restore_tabs directly AND
   the watchdog queued another on the Chrome PID change (live log: 46
   restore runs in bursts, "opened 2 tab(s)" immediately followed by
   "watchdog: chrome pid changed … queueing restore").
5. The extension's LRU eviction (TAB_LIMIT=3) turned the churn into tab
   loss: each duplicate restore re-opened home, and each new tab at the
   limit evicted the LRU real tab (Wikipedia). A full 3-tab restore
   also evicts the FIRST restored tab (it is the LRU by the time the
   third tab lands).

Fix (all four layers):
- restart-api.py: _is_home() helper; snapshot_tabs() EXCLUDES HOME_URL;
  load_snapshot() DROPS HOME_URL from stale snapshots (kills the
  existing pmo.city entry instantly); do_wake no longer spawns its own
  restore thread — sets _need_restore and lets the watchdog's single
  consumer run it (one restore per Chrome start).
- tabbar-extension v1.8.0: evictLRU never evicts a tab created within
  the last 5 s (restore bursts open tabs within seconds; the first
  restored tab survives). Manifest + EXT_VERSION bumped.

Verification:
- Unit (local): _is_home trailing-slash tolerance; load_snapshot drops
  stale home; snapshot_tabs excludes home; home-only browser leaves the
  snapshot untouched. All pass.
- Deployed to scripts volume (read-only-mounted at /etc/neko/supervisord
  in the slots — the volume IS the live file); restart-api restarted on
  both slots (Chrome NOT restarted — active session untouched).
- Live: watchdog rewrote the slot-1 snapshot WITHOUT pmo.city
  (now [PDF, viewer, article]); restore event correctly no-ops
  ("boot skip — 3 tab(s) already present").
- Home now appears ONLY when the browser truly has zero http(s) tabs
  (fresh boot / empty session); it is never persisted, never restored,
  never counted against TAB_LIMIT.

## 28. CloudFiles per-user isolation — Tigo: "not isolated per user" (2026-08-22, live)

Symptom: queued/other users could see the active user's downloads in
CloudFiles ("My downloads"). Screenshots 14:15 UTC: montigaud's PDF
(AI_for_social_good…pdf, 5.4 MB) listed while montigaud was active on
slot-1.

Root cause — router.py CloudFiles route (spec 37 §2.5 fallback):
    k = _state["users"].get(email)
    if k is None:
        k = 1        # ← any user WITHOUT a slot → slot-1's LIVE dir
The router is the single entry (tinyauth → router → slot-<k>:9231), so
every queued/suspended/archived/new user was served slot-1's live
Downloads — i.e. whatever the ACTIVE user on slot-1 had. Downloads
isolation existed only at the slot level (archive/restore per user);
the router fallback bypassed it entirely.

Fix — downloads-api.py is now REQUESTER-KEYED (Remote-Email header):
    resolve_area(email):
      - email == slot's current user (.slot-user.json) → LIVE slot dir
        (writable; new downloads land here);
      - email has /data/sessions/<email>/Downloads archive → THEIR OWN
        archived area (read-only view of their last session);
      - otherwise → empty (no cross-user visibility, ever).
    list_files() → list_files_for(email); /api/files, /file/, /dl/ all
    use the resolved area. Router fallback k=1 is now harmless: any
    slot serves the requester only their own files.

Verification (live, via router with Remote-Email):
  - montigaud@aikumi.pro  → [AI_for_social_good…pdf]        (own archive)
  - spike-user@aikumi.pro → []                              (own live, empty)
  - spike-user2@aikumi.pro→ []                              (no archive yet)
  - stranger@x.pro        → []                              (unknown → empty)
  - /file/… as owner      → 200, application/pdf, %PDF- magic, 5,443,645 B
  - /file/… as non-owner  → 404
Local unit tests (fake slot-user.json + fake sessions archive): owner→live,
archived→own archive, stranger→empty, no-email→empty — all pass.

Note: the black frame in Tigo's screenshots (between two CloudFiles
pages) is a separate observation — the PDF serving path is verified
correct through the router; if "open" still renders black in the kiosk
Chrome (GPU-less PDF viewer), reproduce via CDP before touching it.

## 29. Never stuck on neko LOG IN again — A+B (2026-08-22, live)

Symptom: after expiry, montigaud@aikumi.pro got the neko LOG IN page
again — with the tab bar visible (extension runs there, proven by Tigo's
screenshot) but NO in-page watchdog, so nothing bounced him out.

Root cause: the router injects the in-page watchdog ONLY when its index
fetch of the neko page succeeds; on failure it fell back to _proxy_raw
with NO watchdog. Any page served through that hole (cold-start wake,
neko HTTP not up yet) was permanently stuck. (neko v2.9.0 has no
NEKO_IMPLICIT_AUTH — verified in the binary: only unrelated
implicit_control strings — so there is no server-side "disable login"
toggle.)

Fix A (extension-hosted watchdog, content.js v1.9.0, manifest 1.9.0):
a second watchdog lives in the tab bar extension, which runs on EVERY
http(s) page — including the neko LOG IN screen. Same contract as the
in-page one: /fleet/my-status → state != active → "/" ; active but
LOG IN visible → re-enter via /queue/status open_url. Gate: only when
<neko-connect> exists (the neko app shell) AND host is the router
origin — queue page / landing page / arbitrary sites never bounce.
Same-origin fetch → tinyauth adds Remote-Email → no CORS.

Fix B (router fallback injection, router.py): _proxy_raw now takes
inject_html=True; the fallback path buffers text/html responses,
injects the watchdog, and reframes (transfer-encoding stripped,
authoritative Content-Length — MULTILINE regex, (?im), or the header
lines are not removed). Non-HTML streams byte-identical.

Verification:
  - harness 50/50 PASS (was 43 + 2 new B unit tests: HTML injection +
    reframe, non-HTML byte-identical). The B tests are in-process
    (socketpair) and placed AFTER the finally block so their runtime
    cannot skew the session-clock timing checks.
  - live: router restarted (healthy), montigaud my-status = "queued"
    (queue page, NOT login). Volume updated: router.py + tabbar-
    extension/{manifest.json,content.js}.
  - Chrome was NOT restarted (spike-user ACTIVE on slot-1 — would kill
    his session). Unpacked extensions hot-reload on file change; the
    watchdog is guaranteed from the next page load / session start.
    For an already-stuck page: tab-bar relaunch (or reload) clears it.

## 30. CloudFiles download-only — nothing renders inline (2026-08-22, live)

Tigo decision: "Anything that is a file gets downloaded in cloudfiles.
Period. We display nothing in the embedded chrome browser, we just
download." Kills the whole class of trapped-rendering problems (the
neko Chrome PDF viewer is a chrome-extension:// page where content
scripts are forbidden → no tab bar, no escape; the black frame was the
GPU-less embedded viewer, not the serving path).

Changes (downloads-api.py only — no router, no extension, no compose):
  - UI: "open" action removed; filename + action both link to /dl/<name>
    (attachment). target=_blank dropped (no new tab needed for a
    download).
  - GET /file/<name> now also serves Content-Disposition: attachment
    (closes the inline trap door for bookmarks/direct hits — "period").
  - _serve_file: inline branch deleted; always attachment. Docstring +
    header comment updated.

Verified:
  - local smoke (fake area, slot-user fixture): /dl + /file both
    attachment, bytes intact, non-owner 404.
  - live both slots (volume write + supervisorctl restart downloads-api
    — separate supervisord program, Chrome sessions untouched):
    /dl/ and /file/ on montigaud's McKinsey PDF → 200 attachment
    (application/pdf, %PDF-1.4 magic); page HTML has 0 "open" links and
    only /dl/ hrefs; spike-user on same file → 404.
  - Download in kiosk: Chrome saves silently to the slot's Downloads dir
    (no Save-As prompt by default); file appears in "My downloads" on
    the 3s auto-refresh. Quarantine behavior unchanged (ClamAV'd files
    still "ask the agent to inspect", never served).

## 31. External-site PDFs: built-in viewer disabled (2026-08-22, policy staged)

Tigo hit the trap again OUTSIDE CloudFiles: clicked a PDF link in an
aikumi.news article -> Chrome's built-in PDF viewer opened. CDP DOM
inspection of the live tab proved the mechanism: the tab bar element
(cb-pos-bottom, z-index 2147483647) IS injected into the PDF tab's DOM,
but Chrome's PDFium plugin composites in a layer ABOVE the DOM -> the
bar is invisible -> kiosk trap (no address bar, no back button).
CloudFiles download-only (§30) cannot help external sites.

Fix (matches "we display nothing, we just download", applied
browser-wide): PDFViewerEnabled=false enterprise policy.
  - slot-policy-init.sh v1.2: after stripping Extension* keys, also
    force PDFViewerEnabled=false (idempotent, runs at every container
    start).
  - Deployed to scripts volume + injected into BOTH running slots'
    /etc/opt/chrome/policies/managed/policies.json (22 keys now).
  - PDFViewerEnabled applies at Chrome start (non-dynamic policy):
    montigaud's active session NOT restarted (policy staged for next
    start); verify on next Chrome start that PDF links download
    silently to the slot Downloads dir and surface in CloudFiles
    "My downloads" (same model as §30).
  - Escape during current sessions: Google Docs viewer page carries the
    working tab bar (verified cb-pos-bottom present); PDF tabs are the
    only surfaces where the bar is painted under.

## 32. Tab bar Exit button — user-initiated slot release (2026-08-22, Tigo)

Design agreed with Tigo (chat 2026-08-22): a user who finishes early can
release the slot instead of holding it until the reaper expires them.

### Flow
1. User clicks the Exit button (⏻-style log-out icon, right end of the
   tab bar, red hover) → confirm popup ("Release this slot? Your session
   will be archived and the next person in queue gets it.").
2. Confirm → content script sends SELF_RELEASE to the background worker →
   POST http://127.0.0.1:9230/release (same trusted slot-local path as
   RELAUNCH — works from ANY page, no CORS/cookie issues).
3. restart-api `/release` → `do_suspend("released")`: same teardown as
   the reaper/idle paths (stop chrome → snapshot tabs → archive to
   /data/sessions/<user> → wipe profile → drop member session), then
   notify the router with `{"user", "reason": "released"}`.
4. Router `_release` honours the explicit reason → archive labelled
   reason=released (idle/expired semantics unchanged for other paths);
   queue entry dropped, offer-holds cleared, freed slot re-offered to
   the queue head by the reaper (existing machinery).
5. Content script redirects to the router origin (cached as
   cbRouterOrigin in chrome.storage.local whenever the bar runs on a
   cloudbrowser page; fallback https://cloudbrowser.dev01.pmo.city) →
   queue/landing page. The 2 s watchdog (`/fleet/my-status` →
   state="released") is the backstop if the redirect is lost.

### Re-entry semantics (as built)
- No queue → archive wake (reason != expired) puts the user straight
  back on a free slot — instant reclaim after an accidental exit.
- Queue present → the freed slot goes to the head; the released user
  re-enqueues at the BACK (their queue entry was dropped on release).
This matches "go back in the queue" under contention without an
artificial penalty when the fleet is idle.

### Security
- The browser can only reach the slot's restart-api (127.0.0.1:9230);
  restart-api releases the slot's OWN user (slot_user() from
  .slot-user.json) — a page cannot forge a different target.
- restart-api → router /fleet/release is the existing internal control
  path (no Remote-Email → control-plane guard intact).

### Edge cases
- Reaper race: /suspend and /release are idempotent (do_suspend early-
  returns on _suspended); a racing reaper expiry still archives with the
  correct reason (body reason wins, _expiring fallback preserved).
- Router unreachable: _retry_release retries (reason carried).
- Extension version: content.js VERSION, background EXT_VERSION and
  manifest all bumped to 1.10.0 (kept in sync per the staleness-heal
  contract).

### Files
- scripts/router.py: _release reason pass-through (+docstring).
- scripts/restart-api.py: notify_router_release(user, reason),
  do_suspend(reason), _retry_release(reason), POST /release route.
- scripts/tabbar-extension/content.js v1.10.0: Exit button, confirm
  popup, SELF_RELEASE, router-origin cache, redirect.
- scripts/tabbar-extension/background.js v1.10.0: SELF_RELEASE handler.
- scripts/tabbar-extension/manifest.json 1.10.0.

### Tests (harness 55/55)
- spec32: slot /release → 200
- spec32: released → archived reason=released, slot freed
- spec32: my-status = released (watchdog bounce state)
- spec32: re-entry reclaims the free slot (archive wake)
- spec32: back to active after reclaim

### Spec 32 follow-up (2026-08-22, found live): stale-notify guard
Live deploy test exposed an edge case: the router's self-heal
force-release (user expired, slot never called back) leaves the slot's
.stale slot-user.json stale. A later slot-initiated release (reaper or the
new /release route) then re-notifies the router and OVERWROTE the
archive reason (expired → released), corrupting re-queue semantics.
Fix: `_release` only writes the archive when the user was live (k is
not None) OR no archive exists yet — a stale notify can no longer
clobber a newer reason. Harness: +4 checks (stale unknown user → 200,
release #2, stale idle notify keeps released, A re-entry restore).
