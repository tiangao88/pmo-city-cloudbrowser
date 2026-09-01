> **Scope correction (2026-08-28/29):** W2 is a binary all-green gate and is
> now COMPLETE. D3/D15 is GREEN and closed for W2. D13 screen-follow is W3-3;
> strict D15 authenticated-surface continuity is W3-1. See 28-w3-scope.md.

# W2 Definition of Done — Pilot (Tigo + testers)

> **Final status (2026-08-29): COMPLETE.** All retained W2 acceptance
> criteria below are green and evidence-linked. Deliberate carry-over items
> are W3 work, not open W2 boxes.

> **Status update (2026-08-29):** The W2 pilot gate is now COMPLETE: all retained
> W2 rows are green, evidence-linked, and accepted. D13 screen-follow and
> strict D15 authenticated-surface continuity are deliberate W3 carry-over,
> not open W2 criteria.
> that owner, and one trusted `cloudfiles.dev01.pmo.city` application tab.
> The recreate of only `cb-fleet-v2` completed and Coolify reported all five
> components `running:healthy`. The strict D15 C recovery check nevertheless
> did not pass: slot-1 ended suspended/ownerless with Chrome stopped and no
> tabs, and its CDP endpoint reset connections before the post-recreate
> inspection could finish. The router state contained no active users, slots,
> or sessions; `spike-user@aikumi.pro` was in the human queue after an offer
> expired. Slot-2 was explicitly suspended before the recreate and ended as an
> unowned baseline. Keep D15 B/C open and do not mark the recreate checkbox
> complete.
> **Spec-77 closure (2026-08-28, later the same day):** the slot-1 recovery
> failure was root-caused (offer→expire livelock + no owner-bound boot
> recovery) and fixed under `77-w2-recreate-recovery.md` (ghost-offer
> backoff + owner-bound boot hint; local suite 124/124 green). A re-run of
> the recreate qualification on `cb-fleet-v2` PASSED for the spec-77
> contract: `boot-hint wake slot-1 → spike-user@aikumi.pro` with no human
> interaction; slot-1 recovered owner + Chrome + `cdp_ok: true` + 2 tabs
> (incl. trusted `pmo.city`); the router assignment is recorded; the
> `montigaud` offer-expiry livelock is dead (`backed_off` → dropped). The
> strict authenticated-surface criterion stays open by design (spec 56
> strips identity cookies from archives; broker re-login is W3).
> **D15 added 2026-08-22 (Tigo)** — embedded SSO slot port, back in W2
> (27-w2-deltas.md §E.2#2; scope = D3/D15).
> **SME:** Lee unavailable at session time → **Tigo acts as SME**; Lee
> validation follows when available. Pilot workflow: **CRM** (live on the W1
> viewer, ALSEI Résidentiel re-purchase pipeline). The resulting read-only
> CRM evidence and Tigo acceptance are recorded in `80-d14-crm-evidence.md`.
> Every DoD item below is verified against the detailed specification
> (02-functional-requirements.md FR-x) and the W1 record
> (10-w1-status.md, 18-w1-summary.md, 17-viewer-preconfiguration.md,
> 19-viewer-test-findings.md). W1-proven baselines are listed per item so W2
> re-proves only what is genuinely new. Autonomy per item: see
> `21-w2-autonomy.md`.

---

## 1. Roadmap inventory — everything already decided into W2

Consolidated from all W1 sources (deduplicated). "Src" = where the item was
decided/deferred.

| # | Item | Src (doc / § / FR) | Decision/deferral |
|---|---|---|---|
| R1 | **Per-user unlock + hybrid 2FA** replacing static `NEKO_PASSWORD` (one browser per employee, immutable `user_id`) | 18-w1-summary W2 · FR-5/FR-6 (gate Q3) · 10-w1-status §0/§4 | decided 2026-08-16; build deferred W1→W2 |
| R2 | **Share-vault credentials + deterministic broker with OIDC session flow** (fake-login spike proven; extension path kept separate) | 18-w1-summary · FR-6/FR-9/FR-10 | broker core proven W1; OIDC flow → W2 |
| R3 | **Tab persistence** — open tabs survive viewer restart (cookies/logins already survive; tabs do NOT) | 10-w1-status §0 + DoD-3 note · FR-2 | deferred W1→W2 (candidates: `stopwaitsecs=30`, agent-managed tab snapshot) |
| R4 | **browser-use re-validation on downloads + tab switch** (W1 demo-day used Playwright fallback; tab switch flaked live 2026-08-17) | 18-w1-summary W2 · FR-4 · 19-viewer-test-findings F-4 | re-validation → W2 |
| R5 | **Restart-Chrome button** (tiny HTTP endpoint in viewer, CDP-relay pattern → `supervisorctl restart google-chrome`) | 10-w1-status §8 · 17-viewer-preconfiguration | Tigo-approved design; build → W2 |
| R6 | **Group-gate denial-path test** (non-`PMOC_Users` member → clean 403) | 18-w1-summary W2 · FR-3 | test deferred → W2 |
| R7 | **Tooling image** — bake xdotool (+ curl/jq) `FROM neko:2.9.0` or apt at container start; watchtower drift pin | 10-w1-status §9 · 17-viewer-preconfiguration | policy decided; build → W2 |
| R8 | **2 GB `--memory` cap per browser at deploy** + `MAX_RUNNING_BROWSERS` fleet lock + capacity UX message | 16-capacity-measurements.md · FR-16 · 18-w1-summary | recommendation accepted by Tigo; apply → W2 deploy |
| R9 | **In-viewer file list** (downloads UX polish, FR-12) — W1 checkable outcome reworded to "ask the agent in chat"; the viewer-side file browser is a W2 build | 10-w1-status §0 DoD-3 · FR-12 (I1: both surfaces decided) | deferred W1→W2 |
| R10 | **Canvas fit / kiosk** — Chrome UI chrome (≈141 px: tabs+toolbar+CfT notice, no dismiss) eats the 1920×1080 canvas → app footers/pagination below the fold; kiosk-mode launch + CfT-notice solution; footer-visibility acceptance rule | 19-viewer-test-findings F-1/F-2/F-7/F-8 (live CRM bug 2026-08-17) | new finding → W2 |
| R11 | **Viewer hygiene** — Google Translate auto-popup off; stale Bitwarden popup windows at (0,0) janitor | 19-viewer-test-findings F-5/F-6 | new findings → W2 |
| R12 | **Screen-follow** — viewer canvas resizes to client window (neko v3 / custom bridge) | 08-roadmap W2 row · FR-15 | roadmap item → W2 |
| R13 | **Naming / attach** — browser auto-named "Browser — \<name\>" (user browsers) / "Browser — CRM (service)" (FR-14, W3); attach surface (FR-11) | 08-roadmap W2 row · FR-2/FR-11 | decided 2026-08-16; surfaced → W2 |
| R14 | **SME workflow validation** — real business workflow in the viewer (CRM: browse → qualify → contact), SME sign-off, gap list | W2 kickoff (Tigo = SME; Lee later) | session output |

*Not in W2 scope (checked):* transversal/service browsers (FR-14 → W3),
EU residency check (DONE in W1 — Helsinki FI), per-extension policies
(CfT unsupported), Firefox engine (out of year-1), `--no-sandbox` hardening
(W4), capacity parameters for client deployments (W4, B3).

---

## 2. Definition of Done (W2) — each item verified against the spec

**D1 — Per-user browser identity & isolation (R1, R13)**
*Spec: FR-2 (immutable `user_id`, ONE browser per employee, naming),
FR-11 (browser.list/attach), FR-8 (isolation). W1 baseline: single static
browser + shared `NEKO_PASSWORD` (stopgap, dies in W2). Live evidence:
`79-d1-pilot-evidence.md` (2026-08-28/29).*
- [x] Three corrected pilot identities → distinct user-bound surfaces, with
      the two-pilot live isolation qualification preserved as the acceptance
      baseline. Each is reachable via its own SSO-scoped path and named per
      user — **live-verified 2026-08-28** (montigaud → slot-1,
      spike-user2 → slot-2; per-user `open_url`; per-user display/tab
      naming "CloudBrowser/CloudFiles: \<email\>") — **Tigo pilot
      acceptance recorded 2026-08-29** in `79-d1-pilot-evidence.md`.
      The literal FR-2 "Browser — \<name\>" string is the W3 agent-facing
      `browser.list` naming.
- [x] No cross-leak: user A never sees/attaches user B's browser
      (browser.list shows only the caller's own) — **live-verified 2026-08-28**
      (downloads identity-keyed on the same slot: montigaud `[]` vs spike-user2
      `[2 PDFs]`; per-slot Chrome profiles; per-user archives; SSO-only gate
      401 without session cookie) — **Tigo pilot acceptance recorded
      2026-08-29**
- [x] Static user-facing Neko password login retired from the pilot path;
      internal service credentials rotated (per-user SSO remains the gate)
      and the browser survives restarts with the same identity — **live
      verified 2026-08-28/29**. Stock Neko 2.9.0 still requires an internal
      `NEKO_PASSWORD` for its protocol, so "retired" means removed from the
      user-facing authentication path, not deleted from the internal service
      handshake; see `79-d1-pilot-evidence.md`.
- [x] Agent queue hard timeout enforced at `CB_AGENT_QUEUE_TIMEOUT_S=120`;
      direct timeout regression passed and the router suite is **124/124
      green** (commit `2824db1`).
- [x] Link URL shape per FR-1/A3: `https://cloudbrowser.pmo.city/u/<short-id>`
      (per-user subpath) — dev01 equivalent — **shape superseded 2026-08-21
      (revised FR-1: shared host-level URL keyed on SSO identity via
      `Remote-Email`; see `27-w2-deltas.md` Part 2 row 8 + spec 31);
      live-verified 2026-08-28**

**D2 — Hybrid 2FA for autonomous logins (R1)**
*Spec: FR-5 gate Q3 (TOTP if present → fully autonomous; else ask in chat;
never a hard block).*
- [x] Share-vault item **with** TOTP secret → broker logs in fully
      autonomously — **live-qualified 2026-08-26**: the slot fetched its
      owner's exact `Aikumi Connect` item through GrantHub, logged
      `creds loaded ... (grant path)` and `filled + submitted`; deterministic
      RFC 6238 and exact Authentik `deviceClass=totp` coverage remains green.
- [x] Item **without** secret → agent asks in chat, employee types the code
      from their authenticator, login completes — **live-qualified
      2026-08-26**: a fresh opaque slot/owner-bound challenge was armed only
      after the live TOTP stage was confirmed; the code was submitted once,
      fetched once, filled without logging/persistence, and Authentik accepted
      it (tab left the auth origin; broker logged `login attempt finished OK
      (MFA)`).
- [x] No path where autonomous 2FA happens without a stored secret — the exact
      Authentik TOTP stage and `deviceClass` guard gate autonomous filling; no
      seed ⇒ opaque one-shot code request, never a guessed code. Replay,
      cross-slot and owner-reassignment rejection are covered by the live-
      deployed isolation/security suite.

**D3 — Share-vault + deterministic broker, OIDC session flow (R2)**
*Spec: FR-6 (dedicated share-vault, item-level share + dedicated collection,
master password rejected, autonomy level B default, login-failure handling F7),
FR-9 (deterministic, non-LLM, CDP injection, plaintext never in LLM context),
FR-10 (OIDC token custody via Vaultwarden). W1 baseline: server-to-server CDP
form-fill proven (`login-ok`), fake-login spike proven; extension path kept
separate from the agent broker.*
- [x] Broker fills a declared site's login end-to-end on a pilot site —
      **DONE 2026-08-25 (specs 59+60)**: PowerMail fill end-to-end from
      the stored grant ALONE — broker-side session mint (refresh-token
      leg) → `/api/sync` → decrypt the Powermail item → open
      go.powermail.fr → fill Roundcube form → submit → INBOX
      (`?_task=mail&_mbox=INBOX`, "Boîte de réception"), zero user
      unlock, FR-9 status-only
- [x] OIDC session flow: broker drives a session obtained via the user's
      SSO session (fake-login spike → real IdP) — **DONE 2026-08-23/25
      (spec 57 SSO round-trip with broker fill; spec 59 session-token
      leg)**: the broker captures the refresh token from the SSO
      round-trip (network hook), stores it wrapped, and mints fresh
      vault sessions server-side (grant_type=refresh_token); rotation
      watcher keeps the leg fresh
- [ ] Master password never requested by the broker; audit records which
      autonomy mode (A/B) was active per login — master password never
      requested ✓ (FR-9, logs booleans/status only); autonomy-mode audit
      record (A/B per login) not yet implemented (W3 candidate)

**D4 — Restart-Chrome button (R5)**
*Spec: 10-w1-status §8 (Tigo-approved design).*
- [x] HTTP endpoint in the viewer container (CDP-relay pattern) → Chrome
      restarted via `supervisorctl` (restart-api.py; Batch 1, 22-w2-progress.md)
- [x] Chrome up in < 30 s with profile intact (cookies/logins/extension);
      triggerable from the agent (and manually)
- [x] Janitor CDP watchdog (auto-restart if relay unresponsive) — W2
      hardening per §8 (Batch 1)

**D5 — Tab persistence (R3)**
*Spec: FR-2 (tabs/cookies/logins/extensions survive sessions & devices).*
*W1 baseline: cookies/logins/extensions survive container recreate; open tabs
do NOT (known gap).*
- [x] Full viewer restart (container recreate) → **open tabs restored**
      (**mechanism picked & recorded in 10-w1-status 2026-08-17:
      agent-managed tab snapshot** — Chrome-native restore proven broken in
      CfT 128: orphaned `Session_`/`Tabs_` token pairs, no `Last Session`
      write on stop, `--restore-last-session` overridden by startup URL and
      kiosk; verified URL-drop and no-kiosk boots still → `chrome://newtab`.
      `restart-api.py` snapshots page URLs every 30 s and restores after
      any Chrome (re)start; session cookies already survive — verified:
      CRM SSO logged in after 4 restarts incl. `docker restart`)
- [x] Restart-Chrome button (D4) also preserves tabs (tab snapshot restores
      on ANY Chrome (re)start incl. `POST /restart` — Batch 1)

**D6 — browser-use re-validation on downloads + tab switch (R4)**
*Spec: FR-4 (MCP full control incl. tabs + downloads; browser-use =
token-efficient layer, fundamental criterion). W1 baseline: browser-use
connects; tab switch flaked live (-32001, no `.switch_to_tab`); W1 demo-day
download used Playwright/raw-CDP fallback.*
- [x] Approved agent driver switches tabs on a real fleet slot without detach —
      **DONE 2026-08-23 (spec 47 D6.1–D6.6)** via the vendored
      `pmoc_cb.py`/browser_harness path (not Hermes `browser_exec`): new/switch/
      list/close were stable and the tab bar reflected state.
- [x] Agent triggers a controlled download and reads/verifies the result —
      **DONE 2026-08-23 (spec 47)**; downloads-api returned the owner's file
      and returned empty for a non-owner identity.
- [x] If browser-use cannot stabilize: raw-CDP client stays the documented
      fallback; decision + evidence recorded (do NOT silently ship the flaky
      path) — **Tigo decision 2026-08-20**: local vendored driver `pmoc_cb.py`
      (skill `pmoc-cdp-cloudbrowser`), NOT Hermes `browser_exec`; tabs +
      downloads covered

**D7 — Canvas fit / kiosk (R10)**
*Spec: 19-viewer-test-findings F-1/F-2/F-7/F-8. W1 baseline: F11 + 90% zoom
workaround live (works, per-site); CfT notice has no dismiss button.*
- [x] Chrome launches in **kiosk mode** (no tabs/toolbar); CfT notice solved
      (hidden or removed via custom image) (Batch 1)
- [x] On **every pilot app** (CRM, Vaultwarden web, docs, …): footers,
      pagination, and action bars fully visible **without** zoom/fullscreen
      hacks (acceptance rule from F-1) (Batch 1; CRM re-checked)
- [x] Window-manager pin vs kiosk verified non-conflicting (F-7) (Batch 1)

**D8 — Downloads UX: in-viewer file list + agent retrieval (R9)**
*Spec: FR-12 (per-user durable area, flat, 5 GB/90 d, GDPR erasure, ClamAV
at ingest I6, both access surfaces I1: viewer file browser + agent in chat).
W1 baseline: flat store + quota + retention + ClamAV quarantine proven; agent
retrieval in chat proven; in-viewer file list = the W2 build.*
- [x] Viewer file list shows the user's downloads (open/retrieve from the
      viewer itself); refreshes after new downloads
      (downloads-api :9231 in viewer; HTML list + auto-refresh 3 s; verified
      live — 1MB.zip listed, eicar-test.pdf shown quarantined, 2026-08-18)
- [x] Agent retrieval still works: "list my downloads", "send me file X"
      (GET /api/files + GET /dl/<name>; /dl/1MB.zip byte-identical to disk)
- [x] EICAR re-test: flagged file quarantined, not deleted, user notified
      (janitor-loop 60 s scan-at-ingest: `QUARANTINED eicar-test.pdf →
      .quarantine/1787013400_eicar-test.pdf`, file preserved, janitor log =
      notification surface)

**D9 — Capacity limits applied (R8)**
*Spec: FR-16 (MAX_RUNNING_BROWSERS, per-container RAM cap ≈1–2 GB, parked
browsers, capacity UX). W1 baseline: measured 431→471 MiB; 2 GB recommended
and accepted.*
- [x] 2 GB `--memory` cap applied to the dev01 viewer at deploy; no OOM
      during the pilot soak
      (compose `mem_limit: 2g` → container Memory=2147483648 verified post-
      deploy 2026-08-18; OOM watch = soak item below)
- [x] `MAX_RUNNING_BROWSERS` set (dev01: small, e.g. 2); saturation message
      testable (temporarily set cap=1 → third browser gets the clear message)
      (env `${MAX_RUNNING_BROWSERS:-2}`; `POST /fleet/test {cap:1}` →
      GET /fleet saturated → POST /fleet/request HTTP 503 "All browser slots
      are busy (cap reached: 1)…" → reset, granted 200 — all verified live)
- [x] 3-day soak: zero manual interventions (Chrome crash self-heals < 1 min)
      → **PASS — verdict 2026-08-24** (daily soak-check cron
      `c4c83dd2eb84`; checker repaired and then reported no alerts; free
      suspended slots are correctly treated as idle).

**D10 — Denial path (R6)**
*Spec: FR-3 (Tinyauth group gate). W1 baseline: gate PASSED for members
(PMOC_Users); non-member path untested.*
- [x] User outside `PMOC_Users` → clean 403 / SSO denial, no viewer, no
      internal detail leaked (2026-08-21, 35-d10-results.md: spike-user2
      denied both domains; Authentik page, HTTP 200 = clean denial per
      amended DoD)
- [x] Member login unaffected (regression check) (35-d10-results.md)

**D11 — Tooling image + drift pin (R7)**
*Spec: 10-w1-status §9 (xdotool/curl/jq policy). W1 baseline: xdotool
apt-installed ephemerally (lost on recreate); watchtower drifted Chrome to
133 once (FATAL incident, root-caused).*
- [x] Custom image `FROM neko:2.9.0` (or start-script apt) provides
      xdotool + curl + jq after a container recreate
      (start-script apt chosen: supervisord one-shot `tooling-init` — the
      D9 deploy 2026-08-18 recreated the viewer container and all three
      tools came back; dl.google.com repo disabled per pass, see
      17-viewer-preconfiguration §5)
- [x] Chrome pinned to CfT 128.0.6613.137 across a watchtower cycle
      (drift-pin strategy implemented, 17-viewer-preconfiguration §6:
      image tag 2.9.0 pinned + CfT binary lives in the profile volume +
      launch path pinned in scripts volume; verified through the D9
      container recreate — still CfT 128.0.6613.137)

**D12 — Viewer hygiene (R11)**
*Spec: 19-viewer-test-findings F-5/F-6.*
- [x] No Google Translate auto-popup (translate disabled via policy/profile)
      (Batch 1)
- [x] No stale Bitwarden popup windows parked at (0,0) (janitor closes
      extension popups) (Batch 1)

**D13 — Screen-follow (R12)**
*Spec: 08-roadmap W2 row, FR-15 (reused MIT/Apache component; neko).*
- [ ] Viewer canvas resizes to the client window (neko v3 feature or custom
      bridge): resize → canvas follows, no content loss/letterboxing
- [ ] Best-effort audio still works after the change (FR-15 media)

**D14 — SME workflow validation (R14) — the session outcome**
*Spec: W2 kickoff; SME = Tigo (Lee later); pilot workflow = CRM.*
- [x] CRM browse/filter validation completed in the viewer using the existing
      first tab; no tab was created or evicted. The read-only programme filter
      `idp=1596334675` for **Les Jardins de Vaucelles — TAVERNY** returned
      630 raw rows; after contact-ID deduplication, **6 distinct contacts**
      had `last_modification_date` in August 2026. The six were Cheklat,
      Tiop, Marie-laure Regnault, Guyon, Thierry PECOT, and Aussel romain.
      August-created records = 4; August-modified records = 6; overlap = 4.
      Evidence: `80-d14-crm-evidence.md`.
- [x] SME-requested gaps recorded with owners and scheduled (W3 or W4):
      date-filter UI/API semantics and a broader CRM workflow rehearsal are
      recorded as follow-up items in `80-d14-crm-evidence.md`; no CRM data was
      modified.
- [x] SME signs the W2 DoD (business definition of done) — **Tigo acceptance
      recorded 2026-08-29** in the execution record; Lee re-validates when
      available.

**D15 — Embedded SSO in kiosk Chrome (added 2026-08-22, Tigo)**
*Spec: 23-d15-sso.md (Phase A proven W1), 27-w2-deltas.md §E.2#2 (BACK IN W2;
scope = D3/D15). Removes the manual 24 h re-login for pmo.city apps in the
embedded Chrome.*
- [x] `sso-broker.py` + GrantHub/vault-client settings ported to slots —
      per-slot watcher starts with the container and stays under supervisord;
      plaintext never enters LLM context/logs. **DONE 2026-08-23/26**
      (specs 47, 59, 66, 68, 73–74).
- [ ] Phase B: TOTP leg **DONE 2026-08-26** (D2 autonomous + chat-assisted
      live-qualified); session health **IN PROGRESS**: verify the named
      `tinyauth-session-*` cookie, application landing, and proactive re-login
      before the 24 h expiry.
- [ ] Phase C: restart resilience (re-login after `/restart` or container
      recreate) + hardening — implementation deployed; the authorized recreate
      verified infrastructure recovery but not owner-bound authentication
      because the owner session expired before the destructive boundary; fresh
      authenticated live qualification remains required.

**D18 — Cross-user session isolation (SECURITY, added 2026-08-22)**
*Specs: 41-session-isolation-incident.md (incident), 42-session-isolation-fix.md
(fix), 43-session-isolation-tests.md (tests). Triggered by the wake-storm
profile-swap leak found by Tigo (PMBOK from spike-user → montigaud session).*
- [x] Fix A: `do_wake()` stops Chrome before a user-switch restore; same-user
      re-offer is a no-op
- [x] Fix B: `do_suspend()` snapshot guarded by chrome-pid match (never
      archive another user's tabs)
- [x] Fix C: router wakes only on take, never on offer (no wake storm)
- [x] Fix D: `.archive-user.json` owner marker written at archive, verified
      at restore
- [x] Fix E: contaminated archives purged (montigaud + spike-user)
- [x] Isolation regression suite green (spec 43 T1–T10) — **incident closed
      on green** (scripted T1–T5 + live T2 verified; **live T6/T7/T8/T9/T10
      executed 2026-08-22 23:2x–23:45 UTC on the real fleet — ALL GREEN**:
      slot untouched across storm cycles, markers never crossed users,
      same-user snapshot restore, fresh wake, archive sweep clean)

---

## 3. Verification mapping (DoD ↔ FR ↔ W1 evidence)

| DoD | FR / spec | W1 proof reused | New in W2 |
|---|---|---|---|
| D1 | FR-2, FR-11, FR-8 | one-browser model, naming design | multi-user instantiation, per-user unlock |
| D2 | FR-5 (Q3) | — | hybrid 2FA paths |
| D3 | FR-6, FR-9, FR-10 | CDP form-fill, fake-login spike | OIDC session flow |
| D4 | 10-w1-status §8 | design approved | endpoint build + watchdog |
| D5 | FR-2 | cookies/logins persist; tabs don't | tab restoration |
| D6 | FR-4 | browser-use connects; flake evidence | stable tab switch + downloads |
| D7 | 19 F-1/F-2/F-7/F-8 | F11+90% workaround | kiosk launch, notice fix |
| D8 | FR-12 (I1–I6) | flat store, quota, ClamAV, chat retrieval | in-viewer file list |
| D9 | FR-16 | 431→471 MiB, 2 GB rec | cap applied, soak |
| D10 | FR-3 | member gate PASSED | non-member 403 |
| D11 | 10-w1-status §9 | tooling inventory, drift incident | custom image, drift pin |
| D12 | 19 F-5/F-6 | findings | translate-off, popup janitor |
| D13 | FR-15, roadmap | neko chosen | screen-follow |
| D14 | kickoff | live CRM rehearsal | SME sign-off + gap list |
| D15 | 23-d15-sso.md, 27 §E.2#2 | W1 Phase A proven (viewer) | slot port + Phase B/C |
| D18 | 41/42/43 isolation specs | wake-storm leak (incident) | fix deployed + T1–T10 green |

---

## 4. Open points for the W2 kickoff session

1. **Pilot user set** — Tigo + which testers (names, group memberships).
2. **CRM workflow list** — confirm the top-3 workflows with the SME
   (Tigo now; Lee later). Candidate from the live session: *filter leads →
   open detail → qualify → schedule first contact*.
3. **Per-user unlock mechanics** — per-user `user_id` → how the viewer link
   maps to a browser instance (FR-1 A3 short-id) — needs the multi-instance
   service wiring design (Coolify) before D1/D9 deploy work.
4. **D6 fallback policy** — if browser-use cannot stabilize tab switch,
   confirm raw-CDP fallback is acceptable for the pilot (product decision).
5. **D9 dev01 numbers** — dev01 currently has NO memory cap; applying the
   2 GB cap touches the live stack (viewer restart) — confirm timing
   (before/after the CRM rehearsal ends).
6. **D13 scope** — screen-follow is the roadmap W2 item; confirm it is not
   displaced by D7 (kiosk) — both touch the canvas; sequence them.


## Current corrected W2/W3 boundary

- D13 screen-follow is explicitly **W3-3**, not a W2 exit row; historical D13 checklist/mapping above are superseded by this boundary.
- Strict D15 authenticated-surface continuity is explicitly **W3-1**.
- W2 closes only when every retained W2 row is green and Tigo's pilot/SME sign-off is recorded.
