> **Scope correction (2026-08-28/29):** Retained W2 work is green and closed.
> **D3/D15 is GREEN and closed for W2.** D13 is W3-3; strict D15
> authenticated-surface continuity is W3-1. See 28-w3-scope.md.

# W2 Execution Log (live)

> Companion to 20-w2-dod.md (official DoD) + 21-w2-autonomy.md (autonomy
> register). Updated per work batch; evidence = live verification on the W1
> viewer (dev01). Started 2026-08-17 with Tigo's "go" on D4/D6/D7/D12.

---

## Batch 1 (2026-08-17) — D4 · D6 · D7 · D12 ✅ done & verified

### D5 — Tab persistence ✅
- **Mechanism picked (DoD requirement: "pick and record in 10-w1-status")**:
  **agent-managed tab snapshot** — Chrome-native session restore is broken
  in this profile/Chrome (CfT 128): `Sessions/` holds orphaned
  `Session_`/`Tabs_` token pairs (tokens don't match → nothing restorable),
  no `Last Session`/`Last Tabs` written on stop (`exit_type: Crashed`
  persists), and both the command-line startup URL and `--kiosk` override
  `--restore-last-session` (discriminator tests: URL-drop boot and no-kiosk
  boot both still opened `chrome://newtab`). `stopwaitsecs=30` kept in
  chrome.conf (harmless; helps cookie flush).
- **Implementation** (in `restart-api.py`, no new processes): every
  watchdog tick (30 s) snapshot the http(s) page-URL list to
  `$PROFILE/tab-snapshot.json` (profile volume = survives container
  recreates). On ANY Chrome (re)start — watchdog crash-restart, `POST
  /restart`, or process boot with the browser at an empty state
  (container recreate path) — re-open the snapshot URLs via the plain-HTTP
  CDP endpoints (`PUT /json/new?<url>`), then close leftover
  `chrome://newtab`. Idempotent (skips already-open URLs → no duplicate
  tabs). Pure stdlib (no websocket client) — survives container recreates.
- **Session cookies**: already survive ALL restarts — Chrome persists the
  cookie DB periodically (no fix needed). Verified: CRM SSO still logged in
  (re-purchases pipeline rendering) after 4 consecutive restarts including
  a `docker restart` of the whole container.
- **Verified live (2026-08-17)**: `POST /restart` ×2 → CRM tab restored,
  single tab, logged in; `docker restart` (container restart) →
  boot-restore re-opened the CRM tab, logged in. Log evidence:
  `tab-restore: boot restore (browser at empty state)` / `opened 1 tab(s)
  from snapshot`.
- **Residual (dev-acceptable)**: snapshot only captures http(s) page URLs
  (chrome:// pages intentionally excluded); `boot_restore` fires only when
  the browser comes up at an empty state (won't fight a user who closed
  tabs on purpose between restarts).
- `restart-api.py` + `restart-api.conf` (supervisord program, :9230, stdlib,
  same pattern as cdp-relay). Endpoints: `GET /health` (program states +
  cdp_ok), `POST /restart` (supervisorctl restart google-chrome).
- **Watchdog** (same process): polls local CDP :9222 every 30 s; 3
  consecutive failures → auto `supervisorctl restart google-chrome`.
- Verified live:
  - `POST /restart` → `{"ok": true, "output": "google-chrome: stopped /
    started"}`; healthy again in < 10 s.
  - **Self-heal**: `kill -9` the Chrome pid → CDP down → watchdog restarted
    Chrome; RUNNING + `cdp_ok: true` within ~100 s. (Also covers the D9
    "crash self-heals" acceptance.)
- Agent call path: `http://10.0.37.9:9230/...` (pmoc-lan; not traefik-exposed).

### D6 — browser-use 0.13.8 re-validation on the real viewer ✅
Harness: `d6-revalidation.py` (canonical in hermes-cloudbrowser repo).
- **Tab switch — FIXED**: the supported switch is
  `b.get_or_create_cdp_session(target_id, focus=True)` (moves browser-use's
  agent focus; raw `Target.activateTarget` does NOT). W1 -32001 flake gone —
  verified clean (single-tab start → new tab → switch back → URL reflects).
- **Downloads — FIXED**: browser-use does **not** set
  `Browser.setDownloadBehavior` on externally-attached browsers → W1 files
  silently went to Chrome's default `~/Downloads` (found 1MB.zip there). Fix:
  one call at connect — `Browser.setDownloadBehavior(allow,
  /data/downloads, eventsEnabled)` via `b.cdp_client.send_raw` (browser-level,
  no session). Verified twice: file lands in `/data/downloads` (1048576 B).
- **Known residual (informational)**: `b.downloaded_files` stays empty for
  external browsers (no event wiring) — retrieval reads the per-user area
  directly, so this is tracking-only, not functional.
- **Minor**: `new_page` focus is racy (agent focus doesn't always follow) —
  re-focus after opening a tab (documented in the harness).

### D7 — Canvas fit / kiosk ✅ (CRM footer re-check pending re-login)
- `prepare-chrome.sh`: `--kiosk` (removed `--start-maximized`).
- **CfT notice — GONE**: kiosk alone did NOT remove it (verified on X
  screen), but `--disable-infobars` does (verified: full-screen example.com,
  zero bars). F-2 closed.
- Verified: window state=fullscreen, bounds (0,0,1919×1079), dpr 1,
  `visualViewport.scale` = 1 → **100 % zoom, no workaround**.
- window-manager now skips `windowState=fullscreen` windows (never fights
  kiosk) — F-7 conflict avoided.
- CRM pagination re-check queued for the next logged-in session (session
  cookies dropped by the restart — D5 scope).

### D12 — Viewer hygiene ✅
- **Translate off**: `translate-policy.json` (`TranslateEnabled: false`,
  copied by policy-init) + `translate.enabled=false` pref in
  prepare-chrome.sh. Verified on `chrome://policy`: `TranslateEnabled` →
  `false`, `ExtensionSettings` → Bitwarden force-install intact.
- **Popup janitor** (window-manager.py): extension popup pages
  (`chrome-extension://`, window width < 700) are never pinned fullscreen
  and are closed after 60 s grace. Verified: page-only logic — the Bitwarden
  **service worker** target is untouched; no parked popups at final state.

### Deployed components (canonical: `hermes-cloudbrowser/spike/viewer-neko/`)
`prepare-chrome.sh` (kiosk+infobars+translate pref) · `translate-policy.json`
· `policy-init.conf` (copies translate.json) · `window-manager.py` (kiosk-safe
+ popup janitor) · `restart-api.py` / `restart-api.conf` · `d6-revalidation.py`
· mirror completed with `janitor.py` + `server.py` (were missing from repo).

### Notes / consequences for the pilot
- The Chrome restart **dropped the CRM SSO session cookies** → re-login
  needed for the next CRM session (D5 = tab + login persistence build).
- Tabs: `restore_on_startup=1` still restores only the initial tab in
  CfT 128 (W1 finding re-confirmed) — D5 remains open.

---

## Batch 2 (2026-08-18) — D8 · D9 (deploy) · D11 ✅ done (soak running)

Ran with Tigo's "go" on D8/D9/D11 (autonomy register 21-w2-autonomy.md).
**A5 notify sent before the deploy** (viewer container recreate → neko page
needs a refresh; tabs auto-restore via D5).

### D8 — Downloads UX ✅
- **New `downloads-api.py` (:9231, viewer, pure stdlib)** — both FR-12 I1
  surfaces in one tiny server:
  - viewer: HTML file list (auto-refresh 3 s; open inline / download
    attachment; quarantine badges) — agent opens it on "open my downloads";
  - agent: `GET /api/files` (JSON) + `GET /dl/<name>` (bytes) — the
    "list my downloads / send me file X" surface.
- **Scan-at-ingest made REAL**: janitor container command →
  `python /data/scripts/janitor-loop.py` (60 s loop, compose-level; no more
  manual `supervisorctl start janitor` triggers).
- **Verified live**: `/api/files` lists 1MB.zip; **EICAR re-test** →
  janitor log `QUARANTINED eicar-test.pdf → .quarantine/1787013400_...`
  (file preserved, NOT deleted); `/api/files` shows it quarantined;
  `GET /dl/1MB.zip` → 1 048 576 bytes **byte-identical** to disk.
- **Public route (2026-08-18, revised)**: `https://downloads.cloudbrowser.dev01.pmo.city`
  → viewer:9231, same tinyauth gate (`PMOC_Users`). **Final management
  model (Tigo decision): Coolify UI-managed domain** — Domains tab,
  port 9231, middleware `tinyauth-pmo@file` (identical mechanism to the
  main domain; Coolify injects router labels at render, stored in its DB).
  The compose carries **only** the second tinyauth app-key
  (`<uuid>-downloads`, `config.domain=downloads.cloudbrowser.dev01.pmo.city`).
  First iteration used compose-authored Traefik routers (worked, LE cert
  issued) but was reverted (2026-08-18) to avoid duplicate routers once the
  UI-managed domain lands — composing the route in BOTH places is a
  conflict (two routers, same rule). Verified after revert: no download
  routers on the container, host falls back to Coolify error page (302 →
  on-ai.sbs/error.html), tabs + app-keys intact.

### D9 — Capacity limits ✅ (deploy applied; soak running)
- **Compose patch** (live raw, `docker_compose_raw` PATCH): viewer
  `mem_limit: 2g` + env `MAX_RUNNING_BROWSERS=${MAX_RUNNING_BROWSERS:-2}`.
- **Deployed** via Coolify (restart → stack recreated): container
  `Memory=2147483648` verified; janitor cmd `[python, /data/scripts/
  janitor-loop.py]` verified.
- **Fleet gate** in `restart-api.py`: `GET /fleet` (running/cap/saturated/
  message) + `POST /fleet/request` (200 granted / **503 + clear message**) +
  `POST /fleet/test` (dev hook: cap override, in-memory, documented).
  Demo: cap=1 → saturated → request → HTTP 503 "All browser slots are busy
  (cap reached: 1)…" → clear → granted 200. ✅
- **3-day soak RUNNING** since 2026-08-18 00:41 UTC (kickoff = this
  deploy): daily soak-check cron `c4c83dd2eb84` (06:00 UTC, delivers to
  this chat) — chrome RUNNING / tabs / fleet / memory cap 2.0 GiB /
  janitor-loop. Verdict 2026-08-21.

### D11 — Tooling + drift pin ✅
- **Tooling**: `tooling-init.sh` + conf (supervisord **one-shot**, priority
  0, runs before chrome at every boot) — start-script apt chosen over
  custom image (nothing to build/maintain; works on any neko tag). Pitfall
  fixed: disables the image's `dl.google.com` repo per pass (missing key →
  `apt-get update` fails outright). **Verified through the D9 container
  recreate**: xdotool/curl/jq all back, one-shot EXITED clean.
- **Drift pin** (17-viewer-preconfiguration §6, three independent pins):
  image tag `2.9.0` pinned (watchtower monitor-notify) · CfT 128 binary in
  the profile volume (image refresh can't touch it) · launch path pinned in
  the scripts volume. **Verified through the D9 recreate**: still
  `Google Chrome for Testing 128.0.6613.137`, CRM tab restored (D5
  regression OK).

### Notes / consequences
- Python in the viewer is **3.9** (Debian 11): `X | None` annotations crash
  at import — `from __future__ import annotations` required in all new
  viewer scripts (pitfall recorded in this batch).
- EICAR file stays quarantined on disk (lab-style, never deleted) — the
  `.quarantine/1787013400_eicar-test.pdf` entry is the live evidence.

---

## Batch (2026-08-27) — D15 full recreate qualification — infrastructure pass, owner-auth recovery unproven

- The authorized Coolify recreate of **only `cb-fleet-v2`** completed with all
  five containers healthy. This proves service/container recovery.
- The selected `spike-user@aikumi.pro` session expired and was released before
  the destructive recreate boundary. Consequently, the test did not contain
  an authenticated owner-bound TinyAuth session and cannot prove cookie or
  session recovery.
- Post-recreate read-only inspection preserved the tab set and found no exact
  `tinyauth-session-39fcd0f6` cookie and no trusted application page:
  `authenticated_surface: not-proven`.
- Slot-1 encountered a Chrome policy-init failure during the recreate and was
  initially suspended/ownerless; later live checks showed the policy gate and
  customization receipt present and the owner/tab state recovered. This does
  not change the authentication qualification result.
- Slot-2 recovered cleanly to the zero-tab/homepage baseline, then was returned
  to suspended and ownerless state. No active human session was interrupted;
  no tabs were created or evicted by the verification checks.
- **Result:** D15 B/C remains open. A new qualification must establish a fresh
  owner-bound authenticated session and perform `/restart` and full recreate
  while that session is active.

## Batch (2026-08-28) — D15 C rerun — infrastructure pass, slot-1 recovery failed

- Tigo authorized a fresh recreate/redeploy of **only `cb-fleet-v2`** after
  the leftover `d6-agent@aikumi.pro` slot-2 test session was identified.
- The leftover slot-2 assignment was explicitly suspended first; readback showed
  slot-2 unowned, suspended, Chrome stopped, `cdp_ok: false`, and no tabs.
- Before the destructive boundary, slot-1 held the real test identity
  `spike-user@aikumi.pro`. The read-only baseline passed: Chrome running,
  `cdp_ok: true`, one exact TinyAuth cookie, TinyAuth context HTTP 200 for the
  intended owner, and one trusted `https://cloudfiles.dev01.pmo.city/` page.
- The authorized recreate completed with all five components `running:healthy`.
- Afterward slot-1 ended suspended/ownerless with Chrome stopped, `cdp_ok: false`,
  and no tabs. Its CDP endpoint reset/closed connections before the
  post-recreate cookie/page check could complete. Router state contained no
  active users, slots, or sessions; `spike-user@aikumi.pro` was back in the
  human queue after an offer expired.
- Slot-2 recovered as an unowned running homepage baseline before the final
  readback. No active human session was interrupted and no tabs were created or
  evicted by the read-only checks.
- **Result:** infrastructure recreate = **PASS**; strict D15 C owner-bound
  authenticated session/tab recovery = **NOT PROVEN / FAIL**. The failure is
  isolated to post-recreate slot-1 Chrome/CDP recovery; D15 B/C remains open.

## Batch (2026-08-28) — spec 77 — recreate recovery + ghost-offer backoff CLOSED

- Root cause of the slot-1 post-recreate failure: an unbounded offer→expire
  livelock (`montigaud`/`spike-user` cycling with a 60 s grace neither could
  take) plus an ownerless boot path with no owner-bound recovery. Spec
  `77-w2-recreate-recovery.md` implemented and deployed to `cb-fleet-v2` only:
  per-`(email,slot)` offer-expiry backoff (`backed_off` status, dropped after
  cooldown) and an owner-bound boot hint (`pending_archive_owner` in slot
  `/health`; router 30 s sweep dispatches the standard `/wake` and records the
  assignment; one-shot per boot + router one-shot memory per owner).
- Local suite `test-router.py`: **124/124 green** (2 consecutive runs;
  commits `f301762`, `c9c16e5`, `3e082d0`).
- Live re-qualification (recreate of ONLY `cb-fleet-v2`, both slots
  pre-suspended ownerless): `[router] boot-hint wake slot-1 →
  spike-user@aikumi.pro` fired with no human interaction; slot-1 recovered
  `user: spike-user@aikumi.pro`, `cdp_ok: true`, Chrome RUNNING, 2 tabs
  restored from the archive snapshot (incl. trusted `https://pmo.city/`);
  router state recorded the assignment; `montigaud@aikumi.pro` →
  `backed_off` → dropped (livelock dead, queue empty); slot-2's armed hint
  was not dispatched (owner live on slot-1).
- Read-only post-recreate probe: tab set unchanged, 0 exact TinyAuth cookies
  → `authenticated_surface: not-proven` (spec 56 strips identity cookies from
  archives; broker re-login is W3 out of scope).
- **Result:** spec-77 contract = **PASS**. D15 B/C: infrastructure, owner,
  broker, and snapshot/tab recovery PASS; strict authenticated-surface
  criterion remains open by design (see `23-d15-sso.md`, `76-w2-session-handoff.md`).

---



| DoD | Status | Needs |
|---|---|---|
| D1 per-user browsers | ✅ implementation + live qualification complete 2026-08-29 | corrected three-pilot identities; email labels accepted; Neko internal credentials rotated; agent queue timeout implemented/qualified (commit `2824db1`, 124/124) |
| D2 hybrid 2FA | ✅ done 2026-08-26 | autonomous TOTP + no-seed chat-assisted paths live-qualified; specs 73–74 |
| D3 broker OIDC | ✅ W2 scope closed 2026-08-28 (D3/D15) | GrantHub consumption, OIDC/MFA, session health, owner-bound recovery, and ghost-offer backoff deployed and live-qualified; strict authenticated-surface continuity is W3-1 |
| D4 restart button | ✅ done | — |
| D5 tab persistence | ✅ done 2026-08-17 | mechanism: agent-managed tab snapshot in restart-api.py (Chrome-native restore proven broken — see below); verified POST /restart ×2 + docker restart → tabs restored, login intact |
| D6 browser-use | ✅ done | — |
| D7 canvas/kiosk | ✅ done (CRM re-check) | Tigo re-login |
| D8 file list | ✅ done 2026-08-18 | downloads-api :9231 + janitor-loop scan-at-ingest; EICAR quarantined-not-deleted + agent retrieval byte-identical |
| D9 capacity caps | ✅ deploy + soak PASS; verdict 2026-08-24 | soak cron `c4c83dd2eb84`; no alerts after checker repair |
| D10 denial path | ✅ done 2026-08-21 | spec 35: non-member cleanly denied; member regression unaffected |
| D11 tooling image | ✅ done 2026-08-18 | start-script apt (tooling-init one-shot); drift pin verified through D9 recreate |
| D12 hygiene | ✅ done | — |
|| D13 screen-follow | ➜ W3-3 | A7 approach decision |
| D14 SME validation | ✅ CRM evidence + Tigo acceptance recorded 2026-08-29 | `80-d14-crm-evidence.md`; Vaucelles = 6 distinct August-modified contacts; read-only existing-tab check |
| D15 broker-driven SSO in kiosk Chrome | ✅ W2 scope closed 2026-08-28 (D3/D15) | spec-77 owner-bound recreate recovery + ghost-offer backoff live-qualified (124/124 local suite; boot-hint recovery; livelock dead); strict authenticated-surface continuity is W3-1 by scope |

## Tab bar (Tigo-requested kiosk UI, done 2026-08-18)

Two feature rounds landed in `tabbar-extension/` (MV3, live + both repos):

1. **Nav buttons** — `←` back / `→` forward / `↺` reload on the active
   tab (`chrome.tabs.goBack/goForward/reload`), added beside the existing
   `↻` relaunch. Verified by URL + history-index + navigation-type probes.
2. **Position toggle** — `▲` cycles the bar edge top → right → bottom →
   left; state in `chrome.storage.local` (`cbBarPos`) syncs **all** tabs'
   bars and survives reloads; tabs re-stack vertically on the side edges.

Full button reference + verification: `17-viewer-preconfiguration.md` §9.
Template mirror: `hermes-cloudbrowser` spike + `docs/viewer-preconfiguration.md` §7.

---

## Batch (2026-08-21) — Spec 31 queue + session limits ✅ done & verified

> **D1 closure note (2026-08-29):** the later agent-pool configuration is
> `CB_HUMAN_SLOTS=1` + `CB_AGENT_SLOTS=1`; `CB_AGENT_QUEUE_TIMEOUT_S=120` is
> present in the live router. The timeout implementation is committed in
> `2824db1` and the direct regression returned `status=timeout` (124/124
> router suite).

**Spec 31** (`31-queue-and-session-limits.md`) — unified wait queue +
max session duration for the fleet:

- **Router v3** (`scripts/router-v2.py`, commit `8f97113`): single FIFO
  queue with type-aware head selection + admin jump-ahead (`CB_ADMIN_EMAILS`),
  landing page with **"Open Browser"** button (`/?pwd=…&usr=…` — neko 2.9.0
  auto-login via URL params, params stripped with `pushState`; **neko login
  form removed entirely — SSO is the only gate**), queue page (position +
  adaptive ETA: rolling median of last 50 completed durations, cold start
  `tier max ÷ 2`), **max-duration reaper** (router owns the clock; expiry →
  `POST /suspend` idempotent → archive `reason=expired` → next offer; idle
  suspend from spec 29 still archive-wakes — walk-away ≠ expiry), agent API
  (`POST/GET/DELETE /queue`, Bearer `CB_AGENT_TOKEN`, 202 + instant-grant
  fast path, 501 when token unset), boot hygiene + locking fix
  (`_queue_lock` → `_lock` order, deadlock resolved).
- **Compose**: router env surface `CB_*` + `NEKO_PASSWORD=${NEKO_PASSWORD:-neko}`;
  slots untouched. `CB_HUMAN_SLOTS=1`, `CB_AGENT_SLOTS=0` (human path first).
- **Verified**: local harness `scripts/test-router31.py` **14/14**; deployed
  to `cb-fleet-v2` (dev svc, pre-authorized): compose PATCH (base64-only),
  `router-v2.py` seeded into scripts volume (sha256 `7a3c2238…` = repo =
  container), service restart → 5/5 healthy; **live smoke** — A lands → slot 1
  + Open Browser (`href /?pwd=neko&usr=…`), B lands → queue page
  (`position 1, eta 150s`), fleet/status consistent; **live expiry** —
  after `CB_HUMAN_MAX_SESSION_MIN=5` A suspended/archived `reason=expired`,
  B offered slot, A's next landing → queue page (never neko login).
- Evidence: `36-spec31-results.md`. Agent-slot path deferred
  (`CB_AGENT_SLOTS=0` this iteration, spec 31 §10).

---

## Batch (2026-08-21) — Spec 29 idle suspend/resume + 29b identity sweep ✅

**Spec 29** (`29-idle-suspend-resume.md`) — fleet slots release idle
sessions instead of holding them forever:

- **Reaper** in `restart-api.py`: activity sources `xinput,media,tabs,cdp`
  (X11 idle via ctypes libXss; WebRTC peer via NEKO_EPR sockets; tab-set
  diffs; CDP relay timestamps). Idle ≥ `IDLE_TIMEOUT_MIN` → grace toast
  (tabbar v1.8.0) → suspend.
- **Suspend** = stop Chrome → archive profile (minus cache dirs) +
  Downloads to `sessions:/data/sessions/<user>` → wipe slot profile →
  `POST /fleet/release` (router frees sticky, records archive).
- **Resume** = router archive-wake on first free slot → restore → Chrome
  start → tabs back from snapshot.
- **29b**: router identity sweep (`IDENTIFY_SWEEP_INTERVAL=30`, default)
  re-pushes `{user, slot}` to each slot (`.slot-user.json` in Downloads)
  — kills the stuck-slot failure mode (reaper had no identity after
  router/slot restarts with zero traffic).
- **Compose**: `sessions:/data/sessions` volume both slots; env defaults
  15/5/60 (`IDLE_TIMEOUT_MIN`/`IDLE_GRACE_MIN`/`IDLE_CHECK_INTERVAL`);
  live test timings 2/1/10 (Tigo asked to shorten for the soak); viewer
  pinned `IDLE_ACTION=none`.
- **E2E verified** (slot-2, 1-min timings): identify → idle → grace →
  suspend → archive (194M) → wipe → release → wake → 3 tabs back.
- **Two post-deploy bugs fixed during the soak** (see spec 29 §11):
  (a) `::ffff:127.0.0.1` mapped-loopback counted as a viewer → media
  never idle → reaper blind (fixed exclusion); (b) suspend left
  title-proxy holding the neko member WS → neko kept encoding ~1 core
  (suspend now stops title-proxy, wake restarts it, `/identify` repairs).
- **Deployed files == repo files** (md5-verified 2026-08-21):
  restart-api.py `d6b7d6a8` (spec 31 fresh wake; sha256 `e2222649…`),
  router-v2.py `f6545e12` (spec 31 v3; sha256 `24d24f52…`), cdp-relay.py
  `83812991`, tabbar content.js `87bedac9`.
- **Open (Tigo mandate, not blocker):** healthchecks on fleet slots +
  viewer stack (fleet has router/clamav/janitor only; see spec 29 §11).
- **Soak target corrected 2026-08-21 (Tigo):** the daily soak cron
  (`c4c83dd2eb84`, `soak-check.py` 06:00 UTC) was rewritten to track
  **cb-fleet-v2** (`okixw2fxnwn1lakxvxajodww` — router/slot-1/slot-2/
  janitor/clamav on mother01, discovered by compose-project label), NOT
  the old `cloudbrowser-w1` viewer app (`4guplgcrvug7l7h64m2cxkm1`).
  The fleet + viewer were **stopped via Coolify UI 2026-08-20 ~19:26 UTC**
  (`StopService` in Coolify logs) — containers removed, volumes intact.
  Soak clock restarts when the fleet is restarted; the old 3-day verdict
  date (2026-08-21) only covered the W1 viewer soak and is superseded.
## Batch (2026-08-26) — D2 hybrid 2FA implemented (spec 73) ✅ code, live pending

**D2 — Hybrid 2FA for autonomous logins** (`73-d2-hybrid-2fa.md`):

- **`totp.py`** — deterministic RFC 6238 (HMAC-SHA1, 6 digits, base32 +
  otpauth:// parsing, injectable time). Verified against the RFC 6238
  appendix-B 8-digit vectors (t=59 → 94287082 … t=20000000000 → 65353130).
- **`vault_client.py`** — the broker now reads the CURRENT owner's SSO
  login material from the owner's OWN GrantHub grant (key + session legs):
  mint → sync → decrypt the SSO login item (URI match auth.aikumi.app /
  auth.pmo.city, else name hint) → username/password/TOTP seed. The legacy
  per-owner `sso-creds.json` stays as fallback; no shared identity (spec
  66/67 preserved). Refresh-token rotation persisted on every mint.
- **`sso-broker.py`** — login flow v2: identification fill (unchanged) →
  **MFA handling** on the Authentik TOTP stage
  (`ak-stage-authenticator-validate-code`, `input[name=code]`,
  submit = `button[name=continue]`/`button[type=submit]`, device picker
  support; verified against live Authentik 2025.8.1 + main): seed present →
  autonomous compute+fill (one retry with a fresh code); no seed → router
  `/otp/*` code-exchange → agent asks the employee in chat → broker fills
  the submitted code (single-use, TTL-bounded, never logged). Heartbeat
  watchdog kept alive during MFA waits.
- **`router.py`** — `POST /otp/request` (broker Bearer), `GET /otp/pending`
  (broker Bearer, read-once), `POST /otp/submit` (agent Bearer
  `CB_OTP_AGENT_TOKEN` = new Coolify magic var `SERVICE_PASSWORD_64_OTPAGENT`).
  In-memory only — codes never touch disk/logs; TTL `CB_OTP_TTL_S` (180).
- **Tests**: `test-d2.py` 6/6 (TOTP RFC vectors, secret parsing,
  vault-client decrypt/org-key/find/totp, broker decision + code-exchange
  client, router OTP endpoints incl. fail-closed 403/501, read-once, TTL,
  no-code-in-state). GrantHub regression 34/34; router harness 111/3
  (the 3 spec41 failures are a PRE-EXISTING drift — same failures with the
  pre-D2 repo router; D2 adds zero regressions; tracked separately).
- **Deploy**: files synced to the scripts volume; router env gains
  `CB_OTP_AGENT_TOKEN` + `CB_OTP_TTL_S`; live verification pending Tigo
  (chat-ask leg + autonomous leg).

## Batch (2026-08-21) — session-end UX: neko login watchdog + production timeouts ✅

Follow-up to spec 31 §6b (Tigo report: stuck on neko LOG IN after his
session "expired"):

- **Root cause**: fleet still on fast-test values — slot idle-suspend at
  2 min (`IDLE_TIMEOUT_MIN=2`) killed Tigo's session while he read;
  archive reason was `idle` (resume), not `expired` (re-queue); and the
  already-open neko SPA showed its built-in login when title-proxy
  dropped the WebSocket — nothing redirected the tab to the router.
- **Production values** (Coolify envs, apply on deploy):
  `IDLE_TIMEOUT_MIN` 2→20, `IDLE_GRACE_MIN` 1→5,
  `CB_HUMAN_MAX_SESSION_MIN` 5→30.
- **Router watchdog** (`router-v2.py`): read-only `/fleet/my-status`
  (state: active/queued/idle/expired/new — never transitions state) +
  watchdog injected into the neko index served on the Open Browser flow
  (polls every 5 s; on non-active state redirects the tab to `/` → router
  serves landing (idle → resume) or queue (expired → re-queue)). The neko
  LOG IN can no longer take over an in-flight session.
- **Harness** +3 checks → **17/17 pass** (was 14/14).
- **Deployed**: router-v2.py re-seeded (sha256 `f84cf1fe67…`), service
  restarted 5/5 healthy; live probes confirmed `/fleet/my-status` +
  injected watchdog.
## Batch (2026-08-21) — D9 soak-checker repaired (was blind) ✅

Discovered while compiling W2 status: `soak-check.py` had been ALERTing
since the cb-fleet-v2 rewrite (2026-08-21) because it probed docker-bridge
IPs (10.0.34.x) directly from the Hermes host, which cannot route to
mother01's bridge network (curl 000); the IP inspect template also broke
over SSH (spaces in `{{range .NetworkSettings.Networks}}…`).

**Fixes** (in `/home/hermes/.hermes/scripts/soak-check.py`):
- probes now route via mother01 host (`ssh … curl …`), which reaches its
  own docker bridge
- IP template uses no-space Go syntax `{{range.NetworkSettings.Networks}}`
  (SSH re-splits args with spaces)
- slot alert logic now spec 29/31-aware: a **free** slot's Chrome STOPPED
  is the correct idle-suspended state (was a false positive); only a slot
  with an assigned user must show Chrome RUNNING + cdp_ok (D9 self-heal)

Re-run: **no alerts** — router fleet reachable (montigaud active slot-1),
slot-1 chrome RUNNING/cdp_ok/tabs=1, slot-2 suspended-idle, caps 2.0 GiB /
0.5 CPU, janitor+clamav up.
**Soak clock**: fleet was stopped 2026-08-20 ~19:26 UTC (Coolify UI) and
restarted with today's deploy (~05:00 UTC) → 3-day D9 verdict **2026-08-24**
(pilot day).

## Batch (2026-08-22) — cosmetics + functional clarifications captured, W2 status written ✅

Tigo: "We have done a lot of cosmetic changes and functional clarification.
Make a status and capture all that in our github documentation. Then make a
status on where we are in W2."

- **Status doc:** `38-status-2026-08-22.md` — consolidated record of 9
  cosmetic changes (C1–C9, incl. spec-37 unified top bar, favicon/title,
  numbered queue list, 🌐 non-breaking space) and 9 functional
  clarifications (F1–F9, incl. time-based ETA, offer grace + live
  countdowns, lapsed-offer re-render fix, session limit 30→15 min,
  CloudFiles no-queue routing) with commit refs.
- **W2 position:** 9/14 DoD ✅ · 2 🟡 implemented/design-locked (D1
  per-user isolation — pending sign-off + static-password rotation; D3
  broker-only + GrantHub — Phase B/C pending) · 1 🔄 (D9 soak, verdict
  ≈08-24) · 3 ⏸ blocked on Tigo inputs (D2 2FA test items, D13 A7
  decision, D14 tester names).
- **This batch's own work:** queue-page countdowns (`26f6f0c`), offer-lapse
  freeze fix + render-lapse regression (`eb7b6a6`), session limit 30→15
  (`f2b6ae0`), CloudBrowser pill nbsp (`78decd1`). Harness 43/43, both
  render tests PASS, negative control reproduces the old freeze.
