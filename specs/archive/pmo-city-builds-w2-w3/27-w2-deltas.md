> **Scope correction (2026-08-28):** W2 is a binary all-green pilot gate. D3/D15 is GREEN and closed for W2; D13 is W3-3; strict D15 authenticated-surface continuity is W3-1.

# 27 — W1→W2 Delta, W2 Objective Delta & Definition of Done

> **Status: 2026-08-21.** Snapshot of where the W2 prototype (fleet v2, S7)
> stands relative to (A) what W1 delivered and (B) what W2 is supposed to
> deliver. Sources: `18-w1-summary.md`, `20-w2-dod.md` (official DoD),
> `22-w2-progress.md`, `26-s7-fleet-app.md`, `26-s7-fleet-reproduction.md`.
>
> **2026-08-21 update:** spec 29 idle suspend/resume + 29b identity sweep
> deployed & E2E-verified (idle slots release, archive/resume intact, two
> soak-found bugs fixed — see `29-idle-suspend-resume.md` §10–11). Idle-stop
> refinement (W2 delta list) is now DONE. **§E added 2026-08-21 (Tigo):**
> W1→W2 functional gap analysis + full gap against the W2 DoD. Open:
> healthcheck mandate on fleet slots + viewer stack; fleet soak (both
> stacks stopped via Coolify UI 2026-08-20 ~19:26 UTC); D10/D13/D14.
>
> **2026-08-21 (second update):** spec 31 (unified wait queue + session
> duration limits) integrated as **D16**; W2 to-do reorganized in execution
> order — **§F** below.
>
> **2026-08-21 (third update):** **D17** (slot resource optimization — spec 30
> rollout) added as **#1 execution item**: slots still run heavy defaults
> (1920x1080@30, software VP8, ICE-lite) — the very config that nearly got the
> fleet blacklisted. §F reordered: D17 → soak (now on the tuned fleet) → D16
> (slot counts from post-tuning measurement).
>
> **2026-08-21 (fifth update):** **GrantHub (spec 34)** added to W2 — per-user
> revocable vault-grant app (design + key-read spike done; implementation is
> new code). §F Part 2 row 2, before D2/D3 (broker per-user reads flow through it).
>
> **2026-08-23 (sixth update):** GrantHub rows 1–3 (API, keystore, page) live;
> **D3 capture path ported to the fleet slots and E2E-verified live**
> (§F Part 2 row 4, substeps D3.1–D3.3 below): broker on both slots via
> supervisord, `sso-creds.b64` deployed to the fleet scripts volume, broker
> captures the vault key under the **current** slot owner (startup-only owner
> read was pairing grants under stale identities — fixed), full live chain
> proven on slot-2 (Authentik auto-login → vault unlock → key capture →
> `/connect/grant` POST → status flip → revoke). Remaining D3 legs: broker
> grant consumption (unwrap K_user → per-user vault session) and the OIDC
> delegated-session flow (needs Tigo's A2 IdP test client).
>
> **2026-08-28 update:** Tigo authorized a fresh D15 C recreate/redeploy of only
> `cb-fleet-v2`. The pre-recreate owner-bound authenticated baseline passed for
> `spike-user@aikumi.pro` with one trusted `cloudfiles.dev01.pmo.city` page.
> Infrastructure recovery passed (all five components `running:healthy`), but
> slot-1's post-recreate Chrome/CDP recovery did not: it ended suspended and
> ownerless, and the CDP endpoint reset before post-recreate cookie/page
> inspection completed. D15 C remains open; no user action is currently
> required, but another controlled run is needed after fixing the slot-1
> recovery path.
>
> **2026-08-28 closure (spec 77):** the slot-1 recovery failure was fixed under
> `77-w2-recreate-recovery.md` (ghost-offer backoff + owner-bound boot hint;
> local suite 124/124 green) and the recreate qualification re-ran PASS for
> that contract: `boot-hint wake slot-1 → spike-user@aikumi.pro` with no
> human interaction, owner + Chrome + `cdp_ok: true` + 2 restored tabs
> (incl. trusted `pmo.city`) on slot-1, assignment recorded in router state,
> `montigaud` offer-expiry livelock dead (`backed_off` → dropped). The strict
> D15 authenticated-surface criterion is explicitly W3-1, not a W2 blocker.

---

## A. Delta — W1 (what was delivered) → W2 prototype (current, fleet v2)

**W1 (closed 2026-08-17, DoD 8/8):** ONE shared viewer container (neko +
CfT 128) proving the full chain for ONE user on ONE browser: link → SSO →
browser, agent control via browser-use over CDP, cookie/logout persistence,
downloads (flat store + ClamAV + chat retrieval), Vaultwarden extension.

**W2 prototype (now):** the fleet — N per-user slots behind a first-class
router, built on W1's proven patterns (same image, same scripts-volume
pattern, same CfT decision, same kiosk/tabbar, same restart-api).

| Component | W1 (viewer) | W2 prototype (fleet v2) | Status 2026-08-20 |
|---|---|---|---|
| Topology | 1 container (viewer + janitor + clamav + 2 legacy) | router + 2 slots (+ janitor + clamav) | ✅ live, 5 containers healthy |
| Identity / unlock | shared static `NEKO_PASSWORD` (stopgap, dies in W2) | per-user SSO (tinyauth, PMOC_Users) + sticky routing by `Remote-Email` | ✅ live: spike-user→slot-1, montigaud→slot-2 |
| Isolation | single shared profile | per-slot profile volumes (slots never see each other) | ✅ live |
| Agent control | CDP on the viewer (CfT 128, relay :9223) | **CDP on every slot** (CfT 128 seeded per profile, relay :9223 per slot) | ✅ verified 5/5 probe on both slots, no tunnel |
| Engine | CfT 128.0.6613.137 (pinned, drift-pinned) | same CfT 128, per slot | ✅ |
| Kiosk / tabbar | kiosk + tabbar extension (nav, position toggle, relaunch) | same per slot (tabbar's relaunch now works — restart-api shipped) | ✅ (relaunch fixed 08-20) |
| Homepage | Cloud Files boot URL | **https://pmo.city** (product homepage, Tigo) | ✅ screenshot-verified |
| Restart button (D4) | restart-api :9230 (viewer) | restart-api :9230 per slot (PROFILE_DIR variant) + CDP watchdog + tab restore | ✅ verified live (restart, cdp_ok) |
| Tab persistence (D5) | restart-api snapshot/restore | same mechanism per slot | ✅ |
| Downloads (D8) | downloads-api :9231 + janitor-loop scan-at-ingest (viewer) | ✅ **on slots 08-20**: downloads-api :9231/slot (DOWNLOADS_DIR=/home/neko/Downloads), cloudfiles host live |
| SSO broker (D15) | sso-broker Phase A (auto re-login, shadow-DOM fill) | not on slots | ⏳ B/C pending |
| Fleet gate (FR-16) | dev hook (`/fleet/test cap:1`) in viewer | per-slot fleet endpoint + router busy page (M>N → 503) | ✅ live |
| M>N capacity UX | n/a (single browser) | busy page, resize signal | ✅ verified 3rd user → 503 |
| Idle-stop | n/a | slots idle-stop (35 s) | ⏳ refinement noted |
| Soak | viewer soak RUNNING since 08-18 | fleet soak **starts 08-20/21, verdict 08-21** | ⏳ |

**Net: the W2 prototype is the W1 chain replicated N times behind a router,
plus per-user routing and per-slot agent control.** Nothing W1-proven was
thrown away — every W2 slot uses the same binaries, policies, and service
patterns as the viewer (see `26-s7-fleet-reproduction.md` for the file-level
mapping).

---

## B. Delta — W2 objective (DoD) vs current state

W2 objective (08-roadmap, 20-w2-dod): **PILOT — Tigo + testers run a real
CRM workflow in the browser**, dates Aug 24–30, SME = Tigo (Lee later).
The DoD below is the official definition (see section C).

| DoD | Objective (short) | Current state 2026-08-20 | Delta to close |
|---|---|---|---|
| D1 | Per-user browsers, isolation, naming | ✅ done in fleet form (slots + sticky router) | — (link shape retired 08-21: router keys on SSO identity, URL is host-level) |
| D2 | Hybrid 2FA (TOTP secret → autonomous; else ask in chat) | 🟡 **implemented 2026-08-26 (spec 73)** — broker computes RFC 6238 codes from the owner's vault item (grant path); no seed → `/otp/*` code-exchange → agent asks in chat; live verification pending (Tigo) | live chat-ask + autonomous runs on a real slot |
| D3 | Share-vault deterministic broker, OIDC session flow | ⏳ Phase A done (sso-broker, auto re-login); OIDC flow pending | A2 IdP test client |
| D4 | Restart-Chrome button + watchdog | ✅ done (viewer 08-17, slots 08-20) | — |
| D5 | Tab persistence | ✅ done (mechanism + verified restarts) | — |
| D6 | browser-use re-validation (tab switch + downloads) | ✅ tab switch stable on viewer; per-slot CDP probe 5/5 | re-run browser-use against a slot (agent path) |
| D7 | Kiosk / canvas fit, CfT notice solved | ✅ done (kiosk + no banner, screenshot-verified) | CRM footer re-check on Tigo re-login |
| D8 | Downloads UX: in-viewer file list + agent retrieval | ✅ viewer + **slots deployed 08-20** (downloads-api :9231/slot; cloudfiles.dev01.pmo.city route live, /api/files 200 verified). **Top bar 08-20**: PMO logo + "Cloud Files" wordmark, dynamic email (Remote-Email), 🔒 Secrets + 🌐 Cloud Browser pills; no neko icons. **Surface URLs 08-20**: BROWSER_URL/FILES_URL/SECRETS_URL defined as **Coolify service envs** (fleet + viewer stacks) — survive redeploys, UI-visible, inherited by supervisord children; title-proxy toolbar reads FILES_URL/SECRETS_URL, downloads-api reads BROWSER_URL/SECRETS_URL | — |
| D9 | Capacity caps + 3-day soak | ✅ caps applied (2g, MAX_RUNNING_BROWSERS=2, fleet gate); viewer soak running | **fleet soak verdict 08-21** |
| D10 | Denial path: non-PMOC_Users → clean 403 | ✅ **verified 08-21** (A3 `spike-user2`) — denied on BOTH domains (Authentik permission-denied page); member regression ✅ (`spike-user` → viewer 200). **Decision (Tigo): Option A accepted** — Authentik deny page (HTTP 200) = the clean denial; DoD amended to "clean denial (403-equivalent)" — see `35-d10-results.md` §4 | — |
| D11 | Tooling image + drift pin | ✅ done (tooling-init one-shot, CfT drift-pinned) | — |
| D12 | Viewer hygiene (translate off, popup janitor) | ✅ done | — |
| D13 | Screen-follow (canvas resizes to client window) | ⏳ pending | A7 approach decision |
| D14 | SME workflow validation (CRM: browse → qualify → contact) + sign-off | ⏳ pending | Tigo = SME; Lee later |
| D15 | Broker-driven SSO in kiosk chrome (added 08-18) | ⏳ Phase A done; B (TOTP, session health) + C (restart-recreate soak) pending | two-group quirk (PMOC_Users + AKP_IT_Admin) parked |
| D16 | Unified wait queue + session duration limits (spec 31, added 08-21) | ✅ **implemented & live-verified** (08-21): router v3 (queue, landing, reaper, agent API), deployed on cb-fleet-v2; 14/14 harness + full live acceptance (expiry → archive → offer → re-queue) — see `36-spec31-results.md` | agent path (CB_AGENT_TOKEN) still unset → `/queue` API 501; first-connect click-through still needs Tigo UAT (spec 31 §11) |
| D17 | Slot resource optimization (spec 30 rollout, added 08-21) | ✅ **deployed 08-21 (Tigo, qualify)** — tuned fleet live: `NEKO_SCREEN=1280x720@30`, H264, bitrate 2048, NAT1TO1, ICE-lite off, CPU 0.5; measured `33-d17-results.md` (idle CPU −99%, loaded p95 −77%) | residual: audio/screencap off + agent Chrome memory flags not confirmed; FR-16 numbers in `16-capacity-measurements.md` |

**Shortest path to a passable W2 pilot** (my read): close D8-slots
(downloads surface), D10 (403 test), and D14 (CRM run with Tigo) — D2/D3/D13
can land after the pilot window; D15 B/C is a quality gate, not a blocker.

---

## C. Definition of Done (W2) — official, from `20-w2-dod.md`

**Approved 2026-08-17 (Tigo).** W2 dates Aug 24–30 · Owner: Tigo / PMO City ·
SME: Tigo (Lee validation follows) · Pilot workflow: **CRM** (ALSEI
Résidentiel re-purchase pipeline) on the W1 viewer.

Principles baked into the definition:
- Every DoD item is verified against the detailed spec (FR-x) and the W1
  record; **W1-proven baselines are listed per item so W2 re-proves only
  what is genuinely new.**
- Autonomy per item: see `21-w2-autonomy.md`.
- DoD is business-complete when **the SME (Tigo) signs it** (D14).

The 14 items (condensed from §2 of `20-w2-dod.md`; full checklists there):

1. **D1** Per-user browser identity & isolation (2 pilots, 2 distinct
   browsers, no cross-leak, static NEKO_PASSWORD retired, per-user link).
2. **D2** Hybrid 2FA for autonomous logins (TOTP → autonomous; else ask in
   chat; never a hard block).
3. **D3** Share-vault + deterministic broker, OIDC session flow (master
   password never requested; audit records autonomy mode A/B).
4. **D4** Restart-Chrome button (HTTP → supervisorctl; up <30 s, profile
   intact; janitor CDP watchdog).
5. **D5** Tab persistence (full viewer restart → tabs restored; restart
   button preserves tabs too).
6. **D6** browser-use re-validation on downloads + tab switch (stable; else
   raw-CDP documented fallback — never silently ship flaky).
7. **D7** Canvas fit / kiosk (kiosk mode; CfT notice solved; footers/pagination
   visible on every pilot app without zoom hacks; window-manager non-conflict).
8. **D8** Downloads UX (in-viewer file list + agent retrieval; flat store
   5 GB/90 d; ClamAV at ingest; EICAR quarantined-not-deleted).
9. **D9** Capacity limits applied (2 GB memory cap; MAX_RUNNING_BROWSERS;
   saturation message testable; 3-day soak zero manual interventions).
10. **D10** Denial path (non-member → clean 403; member regression check).
    ✅ **2026-08-21** — non-member `spike-user2` denied on both domains
    (Authentik "Permission denied" page, HTTP 200 — nuance in
    `35-d10-results.md`); member `spike-user` regression ✅ (viewer 200).
11. **D11** Tooling image + drift pin (xdotool/curl/jq after recreate; CfT
    pinned across watchtower cycles).
12. **D12** Viewer hygiene (no Translate popup; no stale Bitwarden popups).
13. **D13** Screen-follow (canvas resizes to client window; audio still works).
14. **D14** SME workflow validation (top-3 CRM workflows executed by tester +
    agent; gaps recorded with owners/schedule; SME signs).

Plus **D15** (added 2026-08-18, Tigo): broker-driven SSO in kiosk chrome —
credential broker (Vaultwarden → CDP injection) drives the tinyauth SSO
login once at browser start; 3 phases (A auto re-login ✅ 08-18, B TOTP +
session health, C restart-recreate soak + hardening).

Verification mapping (DoD ↔ FR ↔ W1 evidence) is in `20-w2-dod.md` §3;
roadmap items explicitly NOT in W2 scope: transversal/service browsers
(FR-14 → W3), per-extension policies, Firefox engine, `--no-sandbox`
hardening (W4), client-deployment capacity params (W4).

---

## Open decisions / gates (from `26-s7-fleet-app.md` §11 + today)

- D-S7-1 personal browser per employee (router, not pool) — **Yes** (locked)
- D-S7-2 pilot slot count — 2 (Tigo + tester); M>N = resize signal
- D-S7-3 cap reached: refuse (busy page), not evict — locked → **superseded 08-21 by spec 31 (D16):** busy page becomes the unified queue; still never evicts a running session (admin jumps the queue, no kick)
- D-S7-4 fleet topology: 1 tenant = 1 fleet — default
- D-S7-5 session creation: auto-create sticky (AUTO_CREATE_SESSIONS=true) — resolved
- D-S7-6 fate of shared viewer: stays during W2, fleet replaces at MVP
- **TODO Tigo:** Coolify prod API key allowed-IPs (gateway egress blocked
  since 08-19; workaround `coolify-local.sh` in place)

---

## D. Downloads routing design — separate files domain behind the same router (DECIDED 2026-08-20, Tigo)

> Covers the D8-on-slots gap: downloads surface on the fleet. Design approved
> in chat; this section records the decision and the router delta. Implementation
> is the D8-on-slots work item (27-w2-deltas.md §B, D8).

### D.1 The shape: one router, two hosts

| Host | Route target | Surface |
|---|---|---|
| `cloudbrowser.dev01.pmo.city` (browser) | `slot-<k>:8081` (neko UI via title-proxy) | the user's browser |
| `cloudfiles.dev01.pmo.city` (files) | `slot-<k>:9231` (downloads-api) | the user's files |

Both hosts are served by the **same fleet router** (no second service, no
second certificate, no second router). Resolution is identical in both cases:
`Remote-Email` (appended by tinyauth) → sticky slot map → that slot's service.

**No per-user URL exists anywhere.** Neither domain varies per user; all
per-user resolution happens inside the router, for both surfaces. Stability
is therefore **neutral** to this decision — both options (separate host and
`/files` prefix) are equally stable in the fleet. The decision rests on the
two criteria below, plus convention, at near-zero cost.

### D.2 Why a separate host, not `/files` on the browser host

1. **Independent ACL (authorization at the door).** Each surface already has
   its own tinyauth app key (`tinyauth.apps.<uuid>-cloudbrowser` and
   `…-cloudfiles`, both `oauth.groups=PMOC_Users` today). Separate host =
   separate gate: the files gate can be tightened/widened (files-only
   access, client-portal group) **without touching the browser gate**, and
   vice versa. With `/files` on the browser host, both surfaces share one
   gate — files-only access is impossible without also granting browser
   access. Pure future-proofing today (both gates are `PMOC_Users`).
2. **Path-namespace ownership.** The browser host serves neko's UI, whose
   path space is not ours (`/ws`, `/api`, Vue assets). The router forwards
   paths raw to the slot. A `/files` prefix on that host rents a namespace
   inside neko's and could collide with a future legitimate neko path. A
   dedicated host has zero collision surface — the contract is explicit.
3. **Convention (cosmetic).** `*.pmo.city` subdomain pattern already
   established (`cloudbrowser`, `cloudfiles` fit it).

**Cost:** near-zero — one more Host rule in the router, DNS, and the label
pair already operated since W1.

**Alternative considered and rejected:** `/files` (or `/cb-files`) on the
browser host. Viable — collision risk is mitigable with a prefix neko does
not own — but it accepts the single-gate limitation and would require
splitting the host later if files-only access ever becomes a requirement.

### D.3 Router delta (implementation)

`router-v2.py` `_route()` gains Host-based dispatch (today it forwards
everything except `/health` to `slot:8081`):

- `Host: cloudbrowser.dev01.pmo.city` → `slot-<k>:8081` (unchanged; s7fleet
  retired by Tigo 08-20)
- `Host: cloudfiles.dev01.pmo.city` → `slot-<k>:9231` (new; `/api/files`,
  `/file/`, `/dl/`, `/`, `/health`)
- `Remote-Email` → sticky slot resolution reused as-is; `/health` stays
  router-local.

**IMPLEMENTED 2026-08-20** (commit `4875238`): Host-dispatch live in
`router-v2.py`; both Traefik URLs point at the router :8081
(`cloudbrowser`/`cloudfiles` app keys, `PMOC_Users`); fleet redeployed;
verified — 401 gates on both hosts, s7fleet → catch-all 307, files surface
200 via router (assigned user).

**FIX 2026-08-20 (commit to follow): keep-alive blind-pipe bug.** The raw
`_pipe` proxy pinned each TCP connection to its first request's upstream, so
a reused connection (browser pool / Traefik upstream pool) carrying a
different Host was served by the WRONG backend — `cloudfiles` showed the neko
page. Fix: non-WebSocket requests force `Connection: close` (per-request
dispatch, connection never reused); `/ws` upgrade still spliced. Reproduced
before (same-conn `cloudfiles /api/files` → 404 from neko), verified after
(conn closed, fresh conns dispatch correctly).

Security carried over unchanged from the viewer-proven `downloads-api.py`:
path safety (unquote + basename, no dotfiles), quarantine surfaced-not-served,
ClamAV at ingest. Trust model unchanged (tinyauth header append — see
`26-s7-fleet-app.md` §6b edge-stripping hardening note).

### D.4 Agent access

Per-slot, over pmoc-lan, as in W1: `GET http://<slot-ip>:9231/api/files` and
`GET /dl/<name>` (byte-identical retrieval proven). **Open design point** (not
in scope of this decision): a fleet-level agent files endpoint — the router
resolving `/api/files` by email (same as D.1) so agents do not need to know
which slot a user is on. Recorded for W3 unless W2 pilot shows a need.


---

## E. W1 → W2 functional gap analysis (Tigo, 2026-08-21)

> Source: live diff of the two scripts volumes on mother01 (`<fleet-uuid>_scripts`
> vs `<viewer-uuid>_scripts`), the §A delta table, and §B DoD state. Note:
> **both stacks were STOPPED via Coolify UI 2026-08-20 ~19:26 UTC** (`StopService`
> in Coolify logs; containers removed, volumes intact) — this analysis is
> file/evidence-based; the prototype as-deployed is currently down and the
> fleet soak clock restarts on restart.

### E.1 Carried over — NOT gaps

| Capability | W1 (viewer) | W2 (fleet slots) |
|---|---|---|
| Downloads + ClamAV quarantine (D8) | downloads-api :9231, flat store 5 GB/90 d, EICAR quarantined-not-deleted | per-slot :9231 + `cloudfiles.dev01.pmo.city` route via router (live 08-20) |
| Tabbar (nav, position toggle, relaunch) | yes | per slot; relaunch fixed 08-20 (restart-api) |
| Restart + watchdog (D4) | restart-api :9230 | per slot :9230 + CDP watchdog + tab restore |
| Tab persistence (D5) | snapshot/restore | same mechanism per slot |
| CDP relay (agent control) | CfT 128, relay :9223 | per slot, CfT 128 seeded per profile, relay :9223/slot (5/5 probe) |
| Kiosk + CfT notice solved (D7) | kiosk, no banner | same per slot (screenshot-verified) |
| Branding / title-proxy | PMO logo + pills | same per slot (FILES_URL/SECRETS_URL/BROWSER_URL as service envs) |
| Translate-off hygiene (D12) | translate-policy.json | slots rely on baked `policies.json` (slot-policy-init preserves non-Extension keys) — **verify once** |
| Isolation | single shared profile (weak) | per-slot profile volumes, sticky routing (**better than W1**) |
| M>N capacity UX | n/a | busy page + resize signal (**W2-only**) |
| Idle suspend/resume | n/a | slots idle-stop 35 s, archive/resume E2E-verified (**W2-only**) |

### E.2 Real functional gaps — W1 had it, W2 slots don't

1. **Secrets-in-browser (Vaultwarden extension) — W1 ✅ / W2 ❌**
   Viewer ships `bitwarden-policy.json` (force_installed ExtensionSettings),
   toolbar pin + xdotool pin-click bootstrap, restart-persistent. Slots have
   **no** bitwarden policy — `slot-policy-init.sh` *strips* all
   `ExtensionInstall{Blocklist,Allowlist,Forcelist}` keys. On a slot the
   🔒Secrets pill opens the Vaultwarden **web UI** (manual login); no pinned
   extension. → affects in-browser vault workflows only; pilot (CRM,
   external site) unaffected. **DROPPED FOR W2 (2026-08-21, Tigo, final):**
   no Vaultwarden extension in the embedded Chrome at all. The broker
   (E.2#2 / D3 / D15) is the single mechanism — it logs the embedded Chrome
   into **any website the user keeps in their Vaultwarden** via CDP. Grant
   mechanism (how the user gives the deterministic broker access to their
   Vaultwarden) = open design question, being resolved 2026-08-21.

2. **D15 SSO broker (auto-login inside kiosk Chrome) — W1 ✅ Phase A / W2 ❌**
   `sso-broker.py` + `sso-creds.b64` + `BROKER_VAULT_*` env exist **only in
   the viewer stack**. The router's tinyauth gate still protects entry, but
   **inside** the slot browser any pmo.city app (cloudfiles, secrets, …)
   needs a **manual SSO login, renewed every 24 h** (session expiry
   `TINYAUTH_AUTH_SESSIONEXPIRY=86400`). W1 auto-re-logged-in after cookie
   wipe. → same pilot impact as #1; B/C (TOTP, session health) pending
   anyway. **BACK IN W2 (2026-08-21, Tigo)** — port `sso-broker.py` +
   `BROKER_VAULT_*` to slots (scope = D3/D15 below).

3. **browser-use end-to-end on a slot — W1 ✅ proven / W2 ⚠️ unproven (D6 partial)**
   W1: browser-use drove the viewer (tab-switch fix, downloads). W2: only
   the **raw-CDP probe 5/5** passed on slots; the actual agent tool was
   never run against a slot. → **close before D14** if the agent is expected
   to execute the CRM workflow itself.

### E.3 Verification gaps — capability present, never proven in W2

- **D10 denial-path 403:** ✅ **CLOSED 2026-08-21** — tested against the
  fleet with A3 `spike-user2`: denied on both domains (Authentik
  permission-denied page), member regression ✅ — see `35-d10-results.md`.
- **D9 fleet soak:** the viewer soak ran 08-18 00:41 → 08-20 19:26 UTC
  (cut ~5 h short of 3 days by the stop); the **fleet soak never ran** —
  daily cron `c4c83dd2eb84` retargeted to cb-fleet-v2 08-21, reports
  "fleet not found" until restart. Zero-manual-intervention verdict:
  **not yet earned for W2.**

### E.4 Full gap against the W2 DoD (D1–D15)

| DoD | W1 evidence | W2 prototype (fleet) 2026-08-21 | Gap class |
|---|---|---|---|
| D1 per-user isolation | single shared viewer | slots + sticky routing, per-slot volumes | ✅ carried (W2 > W1); link shape retired 08-21 (router + SSO identity — FR-1 revised) |
| D2 hybrid 2FA | ⏳ not done | ⏳ not done | 🔴 open (not a W1 gap) |
| D3 share-vault + OIDC broker | sso-broker Phase A (viewer) | **broker not on slots** | ⚠️ partial (gap E.2#2) |
| D4 restart + watchdog | ✅ viewer 08-17 | ✅ slots 08-20 | ✅ carried |
| D5 tab persistence | ✅ viewer | ✅ slots, same mechanism | ✅ carried |
| D6 browser-use re-validation | ✅ viewer (tab switch + downloads) | ⚠️ raw-CDP probe only | ⚠️ partial (gap E.2#3) |
| D7 canvas/kiosk | ✅ kiosk + CfT notice solved | ✅ per slot; CRM footer re-check on Tigo login | ✅ carried |
| D8 downloads UX | ✅ viewer | ✅ slots live 08-20 (downloads-api :9231, cloudfiles route) | ✅ carried; fleet-level agent endpoint = W3 open point |
| D9 capacity + soak | caps ✅; viewer soak ran 3 d (08-18→08-20 cut) | caps ✅ (2g, MAX_RUNNING_BROWSERS=2, fleet gate); **fleet soak never ran** | ⚠️ verification gap (E.3) |
| D10 denial path | ✅ proven in W1 | **never tested** (needs A3 account) | ⚠️ verification gap (E.3) |
| D11 tooling + drift pin | ✅ tooling-init one-shot, CfT pinned | ⚠️ `tooling-init.*` absent from fleet volume — verify drift-pin survives recreate on slots | ⚠️ verify |
| D12 viewer hygiene | ✅ translate off, popup janitor | ⚠️ translate-policy.json viewer-only; slots rely on baked policies | ⚠️ verify |
| D13 screen-follow | ⏳ pending | ⏳ pending (A7 approach) | 🔴 open (not a W1 gap) |
| D14 SME workflow validation | ⏳ pending | ⏳ pilot Aug 24–30, SME = Tigo | 🔴 open (not a W1 gap) |
| D15 broker-driven SSO | Phase A ✅ (viewer) | **not on slots** | ⚠️ partial (gap E.2#2) |

**Net:** nothing W1-proven was thrown away; the three real gaps are the
Vaultwarden extension, the SSO broker, and unproven browser-use on slots.
**Pilot-readiness call:** D14 needs E.2#3 (browser-use vs slot) closed first;
E.2#1 (Vaultwarden extension) is DROPPED for W2 (final — broker-only, see
E.2); E.2#2 (SSO broker on slots) is **back in W2** (row 4/5 scope below);
D10 ✅ closed 08-21 (A3 spike-user2); fleet soak running → verdict ~08-24.

---

## F. W2 to-do — integrated & reorganized in execution order (2026-08-21)

> Spec 31 integrated as **D16** (added to §B/C tables). Spec 34
> (**GrantHub**) integrated 2026-08-21 — design + key-read spike done,
> implementation is new W2 work. Ordering = what unlocks what: soak clock
> first (it runs while we build), quick DoD closes before the new build,
> D16 before the vault/broker tail (queue is pilot-critical), GrantHub
> before D2/D3 (the broker reads per-user vault items *through* GrantHub
> grants), D14 last (it is the pilot). ✅ done · ⏳ pending · 🔵 residual/
> done-in-part.

### Part 1 — Done (W2 progress so far)

| # | Item | State |
|---|---|---|
| D4 | Restart-Chrome + watchdog | ✅ viewer 08-17, slots 08-20 |
| D5 | Tab persistence | ✅ snapshot/restore verified |
| D6 | browser-use re-validation (tab switch + downloads) | ✅ viewer level; residual: re-run vs slot |
| D7 | Kiosk / canvas fit, CfT notice | ✅ verified; residual: CRM footer re-check on Tigo re-login |
| D8 | Downloads UX (in-viewer list + agent retrieval) | ✅ viewer + **slots 08-20**, cloudfiles route live |
| D9⁻ | Capacity caps applied | ✅ 2g, MAX_RUNNING_BROWSERS=2, fleet gate |
| **D17** | Slot resource optimization (spec 30 rollout) | ✅ deployed 08-21 (Tigo, qualify) — tuned fleet live: `NEKO_SCREEN=1280x720@30`, H264, bitrate 2048, NAT1TO1, ICE-lite off, CPU 0.5; measured `33-d17-results.md` (idle CPU −99%, loaded p95 −77%) |
| **D9** | Fleet soak clock | ✅ **started 08-21 ~16:18 UTC** on the tuned fleet — daily check cron `c4c83dd2eb84` (06:00 UTC, report to this group); **verdict due ~08-24 14:30 UTC** |
| **D10** | Denial path (non-member → clean 403; member regression) | ✅ **08-21** — A3 `spike-user2` denied on both domains; member regression ✅ (`35-d10-results.md`; nuance: deny = Authentik page HTTP 200) |
| D11 | Tooling image + drift pin | ✅ CfT drift-pinned |
| D12 | Viewer hygiene | ✅ translate off, popup janitor |
| D15⁻ | SSO broker Phase A (auto re-login) | ✅ 08-18 |
| spec 29 | Idle suspend/resume + 29b identity sweep | ✅ E2E-verified, soak bugs fixed |
| spec 30 | Neko resource research | ✅ committed — informs slot caps |
| spec 31 | Queue + session limits — **design** | ✅ written & locked (implementation = D16) |
| **D16** | Queue + session limits — **implementation (spec 31)** | ✅ **implemented & live-verified 08-21** — router v3 (queue engine, landing page, max-duration reaper, agent `/queue` API), deployed on cb-fleet-v2; 14/14 harness + full live acceptance (expiry → archive → offer → re-queue); evidence `36-spec31-results.md`; residual: agent path (`CB_AGENT_TOKEN` unset → `/queue` API 501), first-connect click-through Tigo UAT (spec 31 §11) |
| spec 63 | Reload hang + PLEASE LOG IN (2026-08-25) | ✅ **fixed & live-verified + user-validated** (`489700e`): stale **X idle clock** re-suspended freshly-woken slots within ~34 s (neko WS drop → login page → hang loop); fix = wake-time idle baseline (`_wake_at` floor + activity markers) — slot gets full IDLE_TIMEOUT budget after every wake; neko `?pwd=&usr=` documented as a **definitive** client constraint (internal-only, user never sees it) |
| spec 64 | Kiosk UX: universal Exit + tab restore + SSO dead-end (2026-08-25) |
| spec 65 | Top-bar Exit (right of email) + session countdown (2026-08-25) | ✅ **implemented, deployed, live-verified** (`1bffdc4`, harness 114/114): architecture finding — the neko top bar is **title-proxy territory** (client page in the user's browser; the extension never runs there, so spec-41/62's ul.menu Exit never reached the user — tab-bar fallback was the only visible one); title-proxy now injects ⏏ Exit (two-step confirm → router `POST /session/release` → slot `/release` teardown, Remote-Email-gated owner-only) + ⏳ mm:ss countdown (`/queue/status` `session_ttl_s`, 15 s poll + 1 s local tick) right of the email; tab-bar Exit stays for external pages (complementary surfaces) | ✅ **fixed, live-verified + user-validated** (`93c6281`, tab bar v1.13.1): (1) Exit **fallback** in the tab bar on external pages (spec 41 top-bar Exit only exists on cloudbrowser pages) — confirm popup anchors **above** the bottom bar (v1.13.1 fixed it rendering off-screen at y≈721/720 — Tigo's "release doesn't work"); (2) snapshot restore was faithful (1 tab = 2 minus the SSO dead-end, now never persisted/restored — Tigo: "that's perfect"); (3) Authentik `binding failed re-evaluation` (#20, order 20) = **benign stock policy** (password-stage skip when backend-authenticated), correlates 1:1 with successful vault SSO authorizations, zero flow errors — nothing to fix in the IdP |

### Part 2 — Historical W2 execution order (now closed)

> **2026-08-29 status:** The dependency-ordered W2 list below is retained as
> the historical execution order, but all retained W2 work is now green and
> W2 is complete. Rows that were formerly described as pending are annotated
> below with their final state. Items deliberately removed from the W2 exit
> gate are W3 work; they are not unfinished W2.

| # | Item | Depends on / notes |
|---|---|---|
| 1 | **O6**: tab bar on error pages — `chrome.webNavigation` listener + inject bar UI on `chrome-error://` (restart always reachable) | ✅ **DONE 2026-08-22** (spec 44): `webNavigation.onErrorOccurred` → bundled `error.html` (failure card + full tab bar, same message protocol); v1.12.0 `79ed0c4`; live-verified slot-2 |
| 2 | **D6**: re-run browser-use against a real slot (agent path) | no deps — fleet tuned & stable (D17 ✅), agent queue/API from D16 ✅; validation-only — **✅ DONE 2026-08-23** (spec 47): agent API → slot-2, vendored driver tab-switch/downloads/navigation all PASS; downloads-api per-user isolation live-verified |
| 3 | **GrantHub (spec 34)**: `…/connect` page + API + per-user key store (wrapped `K_user`), revocation UI + admin kill switch | ✅ **DONE 2026-08-25 (GH.1–GH.8)** — page/API/keystore/revocation live (commits `fbdf8c0` → `f69d28c`); tokens in Coolify **magic variables** (`SERVICE_PASSWORD_64_*`, minted/persisted by Coolify, never in Vaultwarden); relative `GRANTHUB_URL`/`GRANTHUB_STATUS_URL` (`/connect`, `/connect/status`); red Not Shared / green Shared pill state; broker capture live on slots (D3.x below). **Auth-chain foundation — rows 4–6 read per-user vault data *through* its grants** |
| 4 | **D3/D15**: broker OIDC session flow + slot port | ✅ **W2 scope closed 2026-08-28** — GrantHub consumption, refresh rotation, Authentik fill, hybrid MFA, session health, owner-bound recovery, and ghost-offer backoff live-qualified; strict authenticated-surface continuity is W3-1 |
| 5 | **D2**: hybrid 2FA (TOTP → autonomous, else chat ask) | ✅ **DONE AND LIVE-QUALIFIED 2026-08-26** (specs 73–74): owner-grant exact item → autonomous RFC 6238 path; no-seed one-shot chat-assisted path; fail-closed owner/token controls and status-only logs |
| 6 | **D15 B**: named TinyAuth-cookie health + proactive re-login before expiry | ✅ W2 scope closed 2026-08-28 as part of D3/D15; strict authenticated-surface continuity is W3-1 |
| 7 | **D15 C**: restart-recreate resilience + hardening | ✅ spec-77 contract live-qualified 2026-08-28 (124/124); strict authenticated-surface continuity is W3-1 |

| 8 | **D1**: retire user-facing static `NEKO_PASSWORD` login + pilot acceptance | ✅ live-qualified 2026-08-29; internal Neko protocol credentials remain rotated service credentials because stock Neko 2.9.0 requires them; host-level SSO identity replaced the old `/u/<short-id>` shape |
| 9 | **D13**: screen-follow (canvas resizes to client window) | ➜ **W3-3**, explicitly removed from the W2 exit gate |
| 10 | **D7**: CRM footer re-check on Tigo re-login | ✅ **DONE 2026-08-25 (spec 71)** — montigaud's own usable GrantHub grant decrypted exactly one Getunlatch item inside slot-1; broker fill reached `/admin/re-purchases/?mode=CRM`; footer `Lignes par page : 25 / 1 - 25 sur 27678` was fully visible at 100% (`1280×720`, rect y=672..720), with five nearby pagination controls; no zoom/F11 workaround |
| 11 | **O2**: FR-12 downloads-UI wording pick (Tigo decision) | ✅ CloudFiles wording/surface is live; no remaining W2 blocker |

| 12 | **D14**: SME workflow validation (CRM pilot) + sign-off | ✅ **COMPLETE 2026-08-29** — read-only CRM validation and Tigo acceptance recorded in `80-d14-crm-evidence.md` |
| 13 | **O5**: test accounts — A2 Vaultwarden TOTP items (D2/D3), A3 non-member (D10) | ✅ consumed by D2/D3/D10; no remaining W2 blocker |

**Part 2 row 4 — D3 substeps** (broker OIDC session flow + port `sso-broker.py` / `BROKER_VAULT_*` to slots; consumes GrantHub grants):

| # | Substep | State |
|---|---|---|
| D3.1 | Broker as supervisord program on both fleet slots (`26-s7-fleet-slot-sso-broker.conf`) + `sso-creds.b64` deployed to fleet scripts volume (was viewer-stack-only) | ✅ done 2026-08-23 |
| D3.2 | Broker captures under the **current** slot owner — per-pass read of `.slot-user.json` (startup-only read armed capture for a stale owner; observed: broker armed for montigaud while spike-user held slot-1 → `/connect/status` never flipped for the real user). Logs identity changes; capture uses fresh owner | ✅ done 2026-08-23 (live: owner change logged on both slots) |
| D3.3 | Live capture E2E on slot-2: Authentik auto-login (bot creds) → Vaultwarden SSO → unlock → KEY_JS `getUserKey` → `/connect/grant` POST → `/connect/status` `shared:true` → revoke → `shared:false` | ✅ done 2026-08-23 (uid `f470bfd0-…`; correct pairing owner=vault session user) |
| D3.4 | Broker **consumes** the grant server-side: unwrap K_user from the keystore (`/connect/grant` → decrypt) → mint per-user vault session (bw CLI / SDK) → item reads flow through GrantHub; revocation bites (unwrap fails) | ✅ **done 2026-08-25 (spec 59)** — session-token leg implemented + live-verified: refresh token captured from the SSO round-trip (network hook), grant store holds key+session wrapped legs, `usable` = both (green only then); router mints access tokens (grant_type=refresh_token), `/api/sync`, decrypts the Powermail item (AES-CBC-HMAC, MAC ok, pwd len 14); rotation watcher + rotated-token persistence keep the leg fresh; harness 34/34. **Fill e2e DONE (spec 60, 2026-08-25)**: slot-side `pm-fill.py` — grant alone → mint → sync → decrypt → open go.powermail.fr → fill Roundcube → submit → INBOX ("Boîte de réception"), zero user unlock |
| D3.5 | OIDC delegated-session flow: user SSO → broker session; requires A2 IdP test client (O5) | ➜ **W3-2** — dedicated broker IdP client is optional for W2; existing production-like Authentik client is the accepted W2 path |
| D3.6 | **Capture-surface UX (spec 48, incl. rev 2026-08-23)**: every "open a surface" affordance drives the **kiosk**, never a dead-end desktop tab — landing top-bar pills → neko entry `?goto=<surface>`; session-page pills → `POST /kiosk/open` → slot restart-api `/open-url` → live CDP tab (or queued `_pending_start_url` while Chrome is down); `/connect` "Open Secrets" button → kiosk too; non-whitelisted surfaces rejected. **Rev (Tigo 2026-08-23):** the queue page keeps its pills **visible** (hiding them read as "removed") — each carries `data-goto`, a click **POSTs `/queue/goto`** to store a pending intent (whitelisted, never a desktop tab); when the offer is taken the kiosk opens **at that surface** (pending intent consumed in the entry handler). Fixed latent JS bug: `/connect` inline script had an unescaped `broker\'s` → page script never ran ("Checking…" hang) | ✅ done 2026-08-23 — router finalized/committed `cad2650`, pushed; 104/104 harness green; **rev2 shipped `a5ca51b` (Tigo 2026-08-23):** Secrets pill is a **plain main-browser link** (`target=_blank` to Vaultwarden) on *every* bar — never kiosk-forced (the user manages their vault in their fast browser); the GrantHub 🔗 Not Shared/Shared pill is **hidden on the queue bar AND the CloudFiles bar** (no kiosk capture there), retained only where capture matters (landing, session). Queue pill treatment (rev2): CloudFiles = `data-goto` pending intent, Secrets = plain link, no GrantHub pill. Deployed to scripts volume + router restart; 104/104 harness green; queue/landing bars live-verified; session/CloudFiles-bar click-through pending (fail2ban lockout) |

> **2026-08-23 live-test findings folded into D3.2:** (1) the kiosk vault must
> be unlocked **inside the CloudBrowser window** — the broker watches the
> kiosk Chrome only; unlocking in a separate local browser can never be seen.
> `/connect` instruction text updated to say so (router.py). (2) `capture_vault_key`
> blocks the main loop up to 120 s — an SSO redirect mid-capture starves the
> Authentik auto-fill until the capture times out; acceptable for now (capture
> retries), revisit if the SSO window proves flaky.

**Parallel / passive (not blocking rows):**
- **O1** — W1 one-page exec summary — ✅ **done** (`18-w1-summary.md`, committed 2026-08-17; W1 closed 8/8)
- **D9** — fleet soak verdict ~08-24 14:30 UTC (cron `c4c83dd2eb84`, daily 06:00 → this group)

### Open items (parked — tracked, not forgotten)

| # | Item | State / owner |
|---|---|---|
| O1 | W1 **one-page executive summary** (status of everything) | ⏳ not yet drafted — due Aug 23; immediate outstanding deliverable |
| O2 | FR-12 downloads-UI **wording decision** (checkable outcome: "download → see it in viewer" vs viewer file-list) | ⏳ open — deferred to W2; needs Tigo's pick |
| O3 | D17 **deploy + AFTER measurement** | 🔵 prepared 08-21; deploy = Tigo (qualify), measurement = agent after deploy; numbers feed D16 slot counts |
| O4 | Fleet gaps (§E): D10 403 on fleet ✅, fleet soak running (verdict ~08-24), browser-use vs slot = Part 2 row 2 | 🔵 D10 ✅ 08-21; soak live; row 2 open |
| O5 | Test accounts: A2 Vaultwarden TOTP items (D2/D3), A3 non-member (D10) | ⏳ Tigo provides |
| O6 | **Tab bar must render on error pages** — `chrome-error://` doesn't inject content scripts, so the restart button is unreachable exactly when Chrome breaks (ERR_CONNECTION_RESET, 2026-08-21). Fix: `chrome.webNavigation` listener + inject bar UI on error pages (always-available restart affordance) | ✅ **DONE 2026-08-22** (spec 44): error pages replaced by bundled `error.html` (failure card + full tab bar); live-verified on slot-2 (ERR_NAME_NOT_RESOLVED <1s, TIMED_OUT, ERR_ABORTED filter); v1.12.0, commit `79ed0c4` |
| S62 | **Top-bar Exit button** (spec 32→41, gap-closure 2026-08-25) — Exit moved OUT of the tab bar INTO the neko top bar (right of email) per Tigo spec-41 directive; `ensureBarExit()` injects ⏏ button when `/fleet/my-status` state=active; confirm popup → `SELF_RELEASE` → slot `/release` → archive `reason=released` → re-queue; NOT on queue/landing/connect pages (no top bar there, by design). Implemented since 2026-08-22 but never documented → spec 62 adds the missing record | ✅ **VERIFIED LIVE 2026-08-25** (slot-1 active session: exitLi true in ul.menu; my-status active; full chain code-traced) — see `62-topbar-exit-button.md` |
| O7 | **getunlatch URL** — canonical host is `www.getunlatch.com` (apex `getunlatch.com` does not serve: DNS ok, TCP times out from slot → ERR_CONNECTION_RESET). Verified 2026-08-21: `https://www.getunlatch.com/` → 200 → `/en/` from inside the slot. Ensure default tabs / snapshot use the www host | ✅ verified 08-21; snapshot updated on slot-1 |
| O8 | **Watchdog `tab-snapshot.json` gating** (found in live isolation T8) — the W3 snapshot path is gated on `chrome_owns_profile()` pid-match, so the watchdog does NOT write `tab-snapshot.json` during remote-driven sessions (no pid-match while Chrome is owned). Tab persistence in those runs came from the per-user profile archive (Chrome session files) + `do_suspend`'s pre-suspend snapshot — isolation UNAFFECTED, but the watchdog-snapshot gap should be reviewed in W3 (does the snapshot need to be taken from the live profile regardless of pid-match, with owner marking, so restore has a per-user snapshot independent of release path?) | ⏳ open — follow-up from spec 43 live suite (2026-08-22); candidate W3/deltas item, needs design review |

---

## Changelog (append-only)

- **2026-08-25** — **spec 63 + spec 64 closed, user-validated, docs synced.** spec 63 (`489700e`): reload hang / PLEASE LOG IN root-caused (stale X idle clock re-suspended woken slots) → `_wake_at` idle floor, live-verified 4-min hold. spec 64 (`5c64846` → `93c6281`): (a) universal Exit fallback in tab bar for external pages → v1.13.1 fixes the confirm popup rendering **off-screen** below the bottom bar (Tigo: release appeared dead; live geometry re-verified, user confirms Release works); (b) SSO dead-end pages (`auth.pmo.city|auth.aikumi.app/error`) never persisted/restored → 1-tab restore is now expected; (c) Authentik `binding failed re-evaluation` decoded via read-only IdP DB investigation: binding #20 = order-20 Password Stage of `default-authentication-flow` ("Aikumi Connect!", the vault provider's authentication flow) with the **stock** skip-if-backend expression policy — warning is benign, correlates 1:1 with successful vault authorizations, event log has zero flow errors → **nothing to fix in Authentik**. GrantHub row 3 marked ✅ DONE (GH.1–8, magic-var tokens, relative URLs, red/green pill).

- **2026-08-22 (seventh)** — **Isolation suite T6–T10 ALL GREEN on the live fleet** (spec 43, router `596bb72`, commit `2295506`). Maintenance window (Tigo-approved): suspended slot-1, dropped montigaud's stale queue entry (archive preserved; his live tab re-entered once — harmless storm noise), purged tigo-test archive. **T6** storm: slot-1 suspended/STOPPED 16/16 polls over 4 min, offer/expire cycles only, zero wake/take (spec 42 no-pre-wake + spec 46 self-heal held). **T7** isolation replay both directions: marker-A never reached spike-user2, marker-B never reached spike-user (tabs + History verified per archive). **T8** same-user resume: `tab-restore: opened 2 tab(s) from snapshot`. **T9** fresh wake: tigo-test (no archive) → homepage, Chrome RUNNING, no 500. **T10** archive sweep: 6/6 archives marked (2 legacy pre-spec-42 marked retroactively), zero cross-contamination. DoD D18 box updated — isolation class provably dead on the live fleet. **Follow-up added as O8:** watchdog `tab-snapshot.json` gated on `chrome_owns_profile` pid-match (not written in remote-driven sessions; `do_suspend` pre-suspend snapshot covered the release) — candidate W3/deltas design review.
- **2026-08-22** — Part 2 rebuilt on **technical dependencies** (Tigo): execution order = O6 → D6 → GrantHub → D3 → D2 → D15B → D15C → D1 → D13 → D7 → D14, with O1/O2/O5/D9 passive/parallel. D17 + D9 caps confirmed done (live-verified on slots); soak verdict due ~08-24. Also: D15 added to W2 DoD (`20-w2-dod.md`, 29 boxes) + Part 1 D16 row marked implemented.
- **2026-08-22 (second)** — **Part 2 declared the official W2 reference (Tigo)**; O1 marked ✅ done (`18-w1-summary.md`); **O2 + O5 moved into the W2 todo** as rows 11 & 13 (D14 → 12); D9 stays parallel/passive.
- **2026-08-22 (third)** — 🔴 **SECURITY INCIDENT — cross-user session leak** (specs 41–43, DoD D18). Wake-storm profile swap: spike-user's PMBOK tab leaked into montigaud's session/archive (router offer pre-wake + `do_wake` never stopping Chrome). Fix deployed (no profile swap under live Chrome; suspend pid-guard; wake-on-take only; archive owner marker); isolation suite T1–T10 (spec 43). W2 todo **paused → resumed after green**.
- **2026-08-22 (fourth)** — **Incident closed on green** (D18 boxes ticked, `20-w2-dod.md`). Deferred isolation tests **T6/T8/T9 + full T7 marker-tab replay → FIRST item of W3** (Tigo, 2026-08-22; `08-roadmap.md` W3 row + DoD D18 note). Needs a free slot + seeded queue.
- **2026-08-22 (fifth)** — **O6 DONE** (spec 44, tab bar v1.12.0): error pages replaced by bundled `error.html` via `webNavigation.onErrorOccurred` (main-frame, non-abort, http(s) only) — failure card (friendly net::ERR codes) + Retry/Back/Home + full tab bar (same message protocol, zero new SW handlers). Live-verified slot-2: ERR_NAME_NOT_RESOLVED <1 s replacement, ERR_CONNECTION_TIMED_OUT, ERR_ABORTED correctly ignored. W2 todo row 1 → ✅.
- **2026-08-22 (sixth)** — **Black screen + lost-tabs incident (montigaud/slot-1), root-caused, PMBOK tab recovered.** Stream-dead rescue (spec 40) restarted neko 20:26 but left Chrome STOPPED (20:44) → black screen. Manual Chrome start found no tabs: `restore_tabs()` reads only the LIVE profile `tab-snapshot.json`, but idle-suspend had archived the profile at 20:44:55 (PMBOK URL safe in `/data/sessions/montigaud@aikumi.pro/profile/tab-snapshot.json`). Tab re-opened via CDP (PUT `/json/new`, PMBOK rendered, SSO valid). Fix scope filed under **D15 C (row 7)**: restore_tabs archive fallback (slot owner via `.slot-user.json`) + rescue re-arms Chrome after neko restart.
- **2026-08-21** — D16 moved to ✅: spec 31 implemented (router v3) + live-verified on cb-fleet-v2; 14/14 harness; 2 live defects found & fixed (`/wake` 500 for archive-less users, stale `active` queue entries on release); evidence `36-spec31-results.md`. Commits `8f97113` (router v3) + `f3de95f` (acceptance + fixes).

- **2026-08-25 (second)** — **spec 65: top-bar Exit + session countdown** (`1bffdc4`). Tigo: "the exit button is not in the top bar top right — it's in the tab bar at bottom right. Have a look. And implement the countdown immediately." Architecture correction: the neko top bar (email/pills) is the **client page** served by title-proxy — the kiosk extension never runs in the user's browser, so its `ensureBarExit()` (spec 41/62) only ever touched the kiosk's own client-page tab; the user-facing top-bar Exit did not exist. Fixed by injecting into title-proxy's top-bar script: ⏏ Exit (two-step confirm → router `/session/release` → owner slot `/release` → archive reason=released → re-queue; 401/400/502 gating) + ⏳ session countdown (`/queue/status` `session_ttl_s`, 15 s poll / 1 s tick). Harness 114/114 (5 new tests); live-verified injection + endpoint gate. Pitfall documented: `s%60` must be `s%%60` in the Python %-format source.
