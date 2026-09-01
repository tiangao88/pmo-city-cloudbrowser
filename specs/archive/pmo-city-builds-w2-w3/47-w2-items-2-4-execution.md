> **Scope correction (2026-08-28):** D6/GrantHub/D3 W2 acceptance is **GREEN and closed for W2**. D13 is W3-3; strict D15 authenticated-surface continuity is W3-1.

# W2 Execution Checklist — Items 2–4 (D6, GrantHub, D3)

Status: **IN PROGRESS** · D6 + GrantHub core/port complete; D3/D15 live-smoke remediation recorded 2026-08-27 · created 2026-08-22 (Tigo: "proceed with spec/dev/test of items 2 to 4, no validation asks, deploy as necessary") · source rows: `27-w2-deltas.md` Part 2 rows 2–4

> **Resume protocol:** every substep is self-contained; tick it (`[x]`) only
> when verified with evidence noted inline. If interrupted, resume at the
> first `[ ]` tick. Deploys are authorized by Tigo for this scope. Each
> completed step is committed to the repo so state survives any break.

## Execution order (dependency-aware)

1. **D6** (independent — validation-only) → 2. **GrantHub core** (GH.1–3, GH.5–6: router API + crypto + UI + admin, standalone) → 3. **D3 broker port** (D3.1) → 4. **GrantHub capture** (GH.4, rides on the ported broker) → 5. **GrantHub e2e + deploy** (GH.7–8) → 6. **D3 broker-consume + OIDC** (D3.2–D3.6).

---

## Item 2 — D6: browser-use re-validation on a real slot (agent path)

Scope (deltas E.2#3): W1 proved browser-use on the viewer; W2 only the raw-CDP
probe (5/5) passed on slots. Close the gap: run the **agent tool** against a
real slot — tab switch + downloads + navigation — via the vendored driver
(`pmoc_cb.py` / browser_harness), NOT Hermes `browser_exec`.

- [x] **D6.1 — Test identity + agent path config.** Confirm fleet idle (clean); pick test identity (spike-user@aikumi.pro) and agent path. If the agent queue/API is exercised (D16 `POST /fleet/request`, Bearer token), set `CB_AGENT_SLOTS=1` via compose + deploy (Tigo-authorized); else drive the human slot with the test account. *Evidence: fleet/status, compose diff.*
- [x] **D6.2 — Agent obtains a live slot.** Request via agent API (or test account takes slot); verify landing = RUNNING Chrome, `cdp_ok True`, spec-46 wake held. *Evidence: request 200/202, slot /health.*
- [x] **D6.3 — Tab-switch validation.** Agent driver: `new_tab` ×3, `switch_tab`, `list_tabs`, `close_tab` — tab bar reflects state; switching is stable (no crash, no tab loss). *Evidence: driver output.*
- [x] **D6.4 — Downloads validation.** Agent triggers a controlled download; verify it lands in the user's Downloads and is listed by `downloads-api` under the Remote-Email identity (non-owner → empty). *Evidence: downloads-api response.*
- [x] **D6.5 — Navigation/stability.** Short scripted workflow via agent (goto, wait, back/forward, reload); `cdp_ok` stays true throughout; no wedged neko. *Evidence: driver log + /health.*
- [x] **D6.6 — Teardown + report.** Release the slot, restore fleet clean idle; write D6 result into this doc + deltas row 2 + DoD box. *Evidence: fleet/status after.*

## Item 3 — GrantHub (spec 34): `/connect` + API + per-user key store + revoke + admin kill

Scope (spec 34, VALIDATED with red/green buttons): `…/connect` page + API +
per-user wrapped-key store (`K_user`), revocation UI + admin kill switch.
Button states: 🔗 Not Shared **red** → 🔗 Shared **green** (server-side state).

- [x] **GH.1 — Architecture lock (documented in spec 34 §2/§3).** GrantHub runs in the **router container** (same origin, tinyauth gate, `Remote-Email` identity); grant store = per-user folder `/data/sessions/<user>/grant/` (wrapped key + `K_user`); `sessions` volume mounted into the router service (compose change). No central key store.
- [x] **GH.2 — Router: GrantHub routes + API.** Add to router.py: `GET /connect` (page) + `POST /connect/grant` (write wrapped key) + `GET /connect/status` (grant state) + `POST /connect/revoke` + admin `POST /connect/admin/revoke-all` (Bearer secret, mirrors agent-API pattern). All identity via `Remote-Email`. *Evidence: harness routes.*
- [x] **GH.3 — Key-wrap crypto.** `K_user` = per-user random key (secrets module); wrap = AES-GCM; store `{user, wrapped_key, scope="PMO City vault", issued_at, revoked}` in the per-user folder (0600). Master password never stored. Unit tests for wrap/unwrap + revoke-bites. *Evidence: harness.*
- [x] **GH.4 — Capture module (broker-side, rides on D3.1).** `sso-broker.py` (slot) detects the Vaultwarden tab on `secrets.pmo.city`, injects the proven `keyService.getUserKey(userId).toBase64()` read via CDP, POSTs to GrantHub API over TLS; plaintext never logged. *Evidence: live capture with test user.*
- [x] **GH.5 — UI: /connect page + tab-bar buttons.** /connect page: SSO login → redirect to Vaultwarden → capture status → grant confirmation. Tab bar: wire existing 🔗 Not Shared → /connect; flip to 🔗 Shared (green) on granted; click 🔗 Shared → revoke confirm popup → POST revoke → revert (red). State + color read from `/connect/status` on render. *Evidence: screenshots + API calls.*
- [x] **GH.6 — Admin kill switch.** Token-protected `revoke-all`; after kill, every user's unwrap fails. *Evidence: harness + live test.*
- [x] **GH.7 — End-to-end grant test.** Test user on a slot: /connect → SSO → Vaultwarden login → key captured → wrapped + stored → broker unwraps and reads a real vault item. Revoke → re-mint dies. *Evidence: end-to-end logs.*
- [x] **GH.8 — Deploy + live verify.** **DONE 2026-08-25**: compose,
  router and broker deployed; `/connect`, grant/status/revoke, red/green pill,
  admin kill switch and slot grant consumption verified live. GrantHub
  regression remains green (36/36 in D2 closure, spec 74).

## Item 4 — D3: broker OIDC session flow + port `sso-broker.py`/`BROKER_VAULT_*` to slots

Scope (deltas row 4): port the W1 viewer broker to slots; broker consumes
GrantHub grants; OIDC session flow (SSO auto-login for pmo.city apps inside
the kiosk Chrome, 24h session health).

- [x] **D3.1 — Port broker to slots.** **DONE 2026-08-23**: broker runs
  under supervisord on both slots; kill-switch honored; later specs 66/68
  removed the unsafe shared-credential fallback.
- [x] **D3.2 — Broker consumes GrantHub grants.** **DONE 2026-08-25/26**:
  per-slot bearer derives the current owner server-side; `vault_client.py`
  unwraps key+session material, syncs/decrypts the exact SSO item, and
  persists rotated refresh tokens. No shared session-store mount.
- [ ] **D3.3 — OIDC session flow.** Authentik fill and D2 TOTP/no-seed flows
  are live-qualified. Named TinyAuth-cookie health, application landing,
  proactive re-login and restart resilience are implemented and deployed. The
  spec-65 fix (`c7be45e`) also restores `session_ttl_s` for direct active users
  and prevents same-owner identity-sweep generation churn. Authenticated
  owner-bound qualification still needs a fresh MFA code.
- [x] **D3.4 — IdP test path.** **DONE with the existing production-like
  Authentik application and `spike-user` account** for W2 qualification;
  a dedicated `cloudbrowser-broker` client remains optional W3 hardening.
- [ ] **D3.5 — Tests + live verification.** Grant/item read, Authentik fill,
  autonomous TOTP and chat-assisted MFA are live green. Session-health unit
  regression and the spec-65 focused regression are green (`c7be45e`: 8/8;
  router harness 114/114). Live smoke confirmed the timer field, stable marker
  generation across two sweeps, and no further sweep-driven MFA cancellation.
  Remaining: fresh MFA code, authenticated session/proactive-renewal proof,
  `/restart`, and full-recreate qualification.
- [ ] **D3.6 — Report + doc updates.** Code and current qualification status are
  synchronized in GitHub; close after D15 B/C live evidence is complete. The
  sanitized gate evidence is `specs/d15-live-evidence.json`; authentication
  remains blocked by Authentik rejecting the one-time submission, so no
  authenticated-session or restart/recreate claim is made.

---

## Assumptions / clarifications raised before Go

1. **GrantHub key-capture channel** — **CONFIRMED (Tigo, 2026-08-22):**
   capture happens **inside the slot's embedded Chrome** (Vaultwarden page
   there), injected by the broker via CDP — the only proven injector (spike
   2026-08-21 + sso-broker Phase A). The parent-browser wording in spec 34
   §3 is treated as W1-era phrasing; in the W2 pilot the "user's browser" =
   the embedded Chrome. GH.4 rides on the ported broker (D3.1).
2. **GrantHub runs in the router container** (not a new container) — same
   origin, no Caddy surgery; `sessions` volume added to the router service.
   Self-resolved per spec "small web app … same origin".
3. **Admin kill switch** = Bearer-secret endpoint (agent-API pattern), no UI
   page. Self-resolved.
4. **D6 agent path** may need `CB_AGENT_SLOTS=1` for the D16 agent API — a
   compose/env change + deploy (authorized). Self-resolved, noted here.
5. **D3.4 dedicated IdP client is admin-side** (A2b) — will reuse the existing
   client for the port smoke; dedicated client flagged when needed.

---

## Results log (2026-08-23, GH run — evidence for the ticks above)

### D6 (item 2) — completed earlier on 2026-08-23 (commit `c883930`)
- D6.1: fleet clean idle confirmed; `CB_AGENT_SLOTS=1` + fresh `CB_AGENT_TOKEN` (hex, 0600 at `/tmp/cb-agent-token.txt`) live via compose (env UUIDs `b1wzdyr5dletzwgv2ci2saii` / `el8jhvyoqnzo88ddlx5o4464`); router boot log `human_slots=1 agent_slots=1`.
- D6.2: agent `d6-agent@aikumi.pro` → slot-2 via `POST /queue` (200, `{status: active, slot: 2}`, id `q-41`); wake held, Chrome/128.0.6613.137 `cdp_ok true`.
- D6.3: `new_tab`×3 → 5 tabs; `switch_tab` → pmo.city; `close_tab` → 4 remain; tab bar consistent.
- D6.4: `test-download.bin` 1,048,576 B landed in slot-2 `/home/neko/Downloads`; listed by downloads-api direct AND via router (`Host: cloudfiles…`). Per-user isolation live: d6-agent → live dir; montigaud → own archive (`BCG-CEO-Boards-AI.pdf` 1,634,913 B + McKinsey 5,443,645 B, read-only); spike-user → empty.
- D6.5: wikipedia goto+load; `history_back` → example.com; 5 tabs stable; `cdp_ok` true throughout.
- D6.6: `DELETE /queue/q-41` → `{ok:true}`; fleet `users:{} slots:{}`; all tunnels closed.
- Incidental: O6 error page (spec 44) live-verified (unroutable IP → `chrome-extension://hpmocjampkhacpfdabdjblmfkifgkjpd/error.html?e=net::ERR_CONNECTION_REFUSED`).

### GrantHub (item 3) — GH.1–GH.7 done this run
- **GH.1** — locked: router container, per-user `/data/sessions/<user>/grant/`, `sessions` volume added to router service in `26-s7-fleet-compose-v2.yaml` (19-line patch: volume + `GRANT_ROOT` + `CB_GRANTHUB_BROKER_TOKEN` + `CB_GRANTHUB_ADMIN_TOKEN`; slots gain `CB_GRANTHUB_BROKER_TOKEN` + `GRANTHUB_STATUS_URL=http://router:8081/connect/status`).
- **GH.2** — router routes implemented + tested: `test-granthub.py` **24/24 PASS** (boot/req/req2, 501 tokenless, 403 wrong token, grant/status/revoke/revoke-all shapes, 0600 perms, tamper). Full router suite still **94/94** with GrantHub wired in.
- **GH.3** — AES-256-GCM in pure Python (pyaes vendored, `scripts/vendor/pyaes/`): NIST SP 800-38D GHASH/CTR on `pyaes.AES`; cross-validated **200/200 random roundtrips vs `cryptography.hazmat AESGCM`** + known-answer + tamper-rejection. `grant.json` 0600 + per-user `k_user.bin` 0600 (32 B). Master password never stored.
- **GH.4** — broker capture live-proven on slot-2 (see GH.7). Broker fixes required + landed: vault 2026.x `getUserKey()` returns a **Promise** (was sync in the W1 version) → KEY_JS is now async + `eval_js` sends `awaitPromise:true`; userId discovery via localStorage `user_<uuid>_` prefix (no `stateService` exposed on `#/setup-extension`; profile API is 401 without the Bearer token — cookies don't authenticate API calls in this vault).
- **GH.5** — `/connect` page + pill wiring (red/green) covered by endpoint tests; live pill render verified via `/connect/status` flip during GH.7 (deployed UI check pending GH.8).
- **GH.6** — admin revoke-all Bearer-gated (dispatched before the Remote-Email gate); harness-tested; live revoke verified in GH.7.
- **GH.7** — **LIVE e2e PASS (slot-2, host-side test router :18081, scratch grant root):**
  1. Woke slot-2 for `spike-user@aikumi.pro` (hold loop touching `/tmp/cdp-activity` every 20 s keeps the idle reaper off — the REAL fleet router was found to be self-heal-suspending slot-1 every offer cycle, so the e2e ran on slot-2 which the reaper never touches).
  2. Vault login via CDP (plain path): hidden `#email` = `spike-user@aikumi.pro` → `vw-continue-login` → `#masterPassword` → `#/setup-extension` (unlocked).
  3. Broker (slot, `GRANTHUB_URL=http://10.0.34.1:18081/connect/grant`, `CB_GRANTHUB_BROKER_TOKEN=e2e-broker`) → `vault unlocked — capturing (uid=f470bfd0-bbf0-479f-9dc9-cb15a52c1506)` → `grant POST OK`.
  4. Store: `grant.json` (322 B, `-rw-------`) + `k_user.bin` (32 B, `-rw-------`).
  5. `GET /connect/status` → `{shared:true, granted_at:2026-08-23T08:45:01Z, revoked:false}`.
  6. **Unwrap roundtrip MATCH**: `unwrap()` returns the exact captured key `30+0Rrd8Woj…ilcvQ==` (88 chars, 64-byte) — captured ≠ stored ≠ unwrapped mismatch impossible.
  7. **Revoke live**: `POST /connect/revoke` → `{shared:false, revoked:true}`; `unwrap()` after revoke raises `GrantError` (kill-switch bites).
- **GH.8** — ⏳ pending: compose PATCH + deploy (Tigo pre-authorized), volume sync (`router.py`+`granthub.py`+`gcm.py`+`vendor/pyaes`+`sso-broker.py`+slot broker conf → `okixw2fxnwn1lakxvxajodww_scripts`), router restart, live grant/revoke on the real router, harness regression. Deployed router.py baseline md5 `c9ace35798b7e394b0d7f0c18506bd36` (spec-46); local `router.py` (GrantHub, 94/94) is the deploy source.

### Environment notes for the deploy
- Real fleet router (`router-okixw2fxnwn1lakxvxajodww`, IP 10.0.34.5) is cycling offer→expire on slot-1 only (queue: montigaud waiting, spike-user2 waiting, spike-user waiting) — harmless but keeps slot-1 suspended; do not run slot-1-based tests until cleared.
- Test router for e2e: host `/tmp/gh-e2e/` (router/granthub/gcm/sso-broker + pyaes), pid 645064 on :18081, scratch grants at `/tmp/gh-e2e/grants`.
- Slot-2 cleaned after the run: brokers killed, hold loop killed; slot left idle (will self-suspend).
