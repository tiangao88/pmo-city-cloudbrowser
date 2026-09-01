# W2 Execution Checklist — Items 2–4 (D6, GrantHub, D3)

Status: **IN PROGRESS** · created 2026-08-22 (Tigo: "proceed with spec/dev/test of items 2 to 4, no validation asks, deploy as necessary") · source rows: `27-w2-deltas.md` Part 2 rows 2–4

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

- [x] **D6.1 — Test identity + agent path config.** ✅ 2026-08-23: `CB_AGENT_SLOTS=0→1` + `CB_AGENT_TOKEN=<hex, 0600 /tmp/cb-agent-token.txt>` patched via Coolify envs (per-env PATCH), deployed; router log `human_slots=1 agent_slots=1 agent_token=set`. *Evidence: deploy + router boot log.*
- [x] **D6.2 — Agent obtains a live slot.** ✅ Agent API `POST /queue` (Bearer) → `200 {queue_id: q-41, status: active, slot: 2}`; slot-2 wake → `cdp_ok=True, Chrome RUNNING` (Chrome/128.0.6613.137). *Evidence: API response + /health.*
- [x] **D6.3 — Tab-switch validation.** ✅ vendored driver (pmoc_cb + browser_harness CLI over SSH tunnel): `new_tab` ×3 (example.com, pmo.city, wikipedia) → 5 tabs, `switch_tab` → on pmo.city, `close_tab` → 4 remain. *Evidence: harness output.*
- [x] **D6.4 — Downloads validation.** ✅ browser-level `Browser.setDownloadBehavior` (allow, /home/neko/Downloads) + navigation → `test-download.bin` 1048576 bytes landed in slot-2 Downloads; listed by downloads-api direct AND via fleet router (`Host: cloudfiles…` + Remote-Email). Per-user isolation live-verified: d6-agent (owner) → live slot dir; montigaud (archived) → own archived Downloads (BCG/McKinsey PDFs, read-only); spike-user (nothing) → empty. *Evidence: ls + API listings.*
- [x] **D6.5 — Navigation/stability.** ✅ goto en.wikipedia.org/wiki/Cloud_computing + load, `history.back()` → example.com, 5 tabs stable, cdp_ok held. *Evidence: harness output.*
- [x] **D6.6 — Teardown + report.** ✅ `DELETE /queue/q-41` → `{ok: true}`, fleet `users: {} slots: {}`; test http.server killed, tunnels closed (2 stale pre-existing tunnels also found + closed). This report. *Evidence: fleet/status.*

## D6 results — 2026-08-23 (agent path on a real slot, ALL PASS)

Run: `CB_AGENT_SLOTS=1` + fresh `CB_AGENT_TOKEN` on cb-fleet-v2; agent
`d6-agent@aikumi.pro` → slot-2 via `POST /queue` (200 active); driven with
the vendored driver (pmoc_cb + browser_harness CLI) over SSH tunnels.

| Step | Result | Evidence |
|---|---|---|
| D6.1 agent path config | ✅ | envs patched + deployed; router boot `agent_slots=1 agent_token=set` |
| D6.2 slot obtain + wake | ✅ | `POST /queue` → `{status: active, slot: 2}`; `cdp_ok=True` Chrome/128 |
| D6.3 tab ops | ✅ | new_tab×3 → 5 tabs; switch_tab → pmo.city; close_tab → 4 remain |
| D6.4 downloads | ✅ | `test-download.bin` 1048576 B in slot-2 Downloads; listed direct + via router; per-user isolation: owner→live, archived→own archive, unknown→empty |
| D6.5 navigation | ✅ | wikipedia goto+load; history_back → example.com; 5 tabs stable |
| D6.6 teardown | ✅ | `DELETE /queue/q-41` → ok; fleet users/slots empty; servers + tunnels closed |

### Findings (driver + fleet)

1. **browser_harness daemon sends `Browser.*` CDP to the PAGE session, where
   `Browser.setDownloadBehavior` is silently ignored** → downloads never
   started via `cdp("Browser.setDownloadBehavior", …)`. Fix: send it on the
   **browser-level** WebSocket (`/json/version` → `webSocketDebuggerUrl`,
   `{"id":1,"method":"Browser.setDownloadBehavior",…}`). After that, a
   navigation to an `application/octet-stream` URL downloads cleanly. → patched
   into the pmoc-cdp-cloudbrowser skill.
2. **github.com is NOT reachable from the slot** (error page); example.com and
   en.wikipedia.org are. The download test used a file served from mother01 via
   the docker gateway (`http://10.0.34.1:8765/…`). PMO-city egress may block
   github — worth a note for D14/agent workflows that fetch from github.
3. **downloads-api per-user resolution confirmed live**: owner → live slot
   Downloads (writable); archived user → own `/data/sessions/<email>/Downloads`
   (read-only); unknown → empty. This closes the CloudFiles isolation question
   from 2026-08-22 — the earlier `[]` probe predates this fleet config.
4. O6 (spec 44) error page incidentally live-verified: unroutable IP →
   `chrome-extension://…/error.html?e=net::ERR_CONNECTION_REFUSED`.

### Agent-path config left in place (deliberate)

`CB_AGENT_SLOTS=1` + `CB_AGENT_TOKEN` stay live — the D16 agent API is proven
and later steps (D3 broker, GrantHub) redeploy anyway. Token stored 0600 at
`/tmp/cb-agent-token.txt` (agent-side copy; Coolify env holds the value).

---

## Item 3 — GrantHub (spec 34): `/connect` + API + per-user key store + revoke + admin kill

Scope (spec 34, VALIDATED with red/green buttons): `…/connect` page + API +
per-user wrapped-key store (`K_user`), revocation UI + admin kill switch.
Button states: 🔗 Not Shared **red** → 🔗 Shared **green** (server-side state).

- [ ] **GH.1 — Architecture lock (documented in spec 34 §2/§3).** GrantHub runs in the **router container** (same origin, tinyauth gate, `Remote-Email` identity); grant store = per-user folder `/data/sessions/<user>/grant/` (wrapped key + `K_user`); `sessions` volume mounted into the router service (compose change). No central key store.
- [ ] **GH.2 — Router: GrantHub routes + API.** Add to router.py: `GET /connect` (page) + `POST /connect/grant` (write wrapped key) + `GET /connect/status` (grant state) + `POST /connect/revoke` + admin `POST /connect/admin/revoke-all` (Bearer secret, mirrors agent-API pattern). All identity via `Remote-Email`. *Evidence: harness routes.*
- [ ] **GH.3 — Key-wrap crypto.** `K_user` = per-user random key (secrets module); wrap = AES-GCM; store `{user, wrapped_key, scope="PMO City vault", issued_at, revoked}` in the per-user folder (0600). Master password never stored. Unit tests for wrap/unwrap + revoke-bites. *Evidence: harness.*
- [ ] **GH.4 — Capture module (broker-side, rides on D3.1).** `sso-broker.py` (slot) detects the Vaultwarden tab on `secrets.pmo.city`, injects the proven `keyService.getUserKey(userId).toBase64()` read via CDP, POSTs to GrantHub API over TLS; plaintext never logged. *Evidence: live capture with test user.*
- [ ] **GH.5 — UI: /connect page + tab-bar buttons.** /connect page: SSO login → redirect to Vaultwarden → capture status → grant confirmation. Tab bar: wire existing 🔗 Not Shared → /connect; flip to 🔗 Shared (green) on granted; click 🔗 Shared → revoke confirm popup → POST revoke → revert (red). State + color read from `/connect/status` on render. *Evidence: screenshots + API calls.*
- [ ] **GH.6 — Admin kill switch.** Token-protected `revoke-all`; after kill, every user's unwrap fails. *Evidence: harness + live test.*
- [ ] **GH.7 — End-to-end grant test.** Test user on a slot: /connect → SSO → Vaultwarden login → key captured → wrapped + stored → broker unwraps and reads a real vault item. Revoke → re-mint dies. *Evidence: end-to-end logs.*
- [ ] **GH.8 — Deploy + live verify.** Compose change (router sessions mount) + router.py + broker capture to VOL; deploy; verify /connect reachable, grant/revoke live, no regression (harness still green). *Evidence: fleet/status, live grant/revoke.*

## Item 4 — D3: broker OIDC session flow + port `sso-broker.py`/`BROKER_VAULT_*` to slots

Scope (deltas row 4): port the W1 viewer broker to slots; broker consumes
GrantHub grants; OIDC session flow (SSO auto-login for pmo.city apps inside
the kiosk Chrome, 24h session health).

- [ ] **D3.1 — Port broker to slots.** `sso-broker.py` + `sso-creds.b64` + `BROKER_VAULT_*` env → slot supervisord (shared scripts volume + compose env); kill-switch `SSO_BROKER_ENABLED` honored; deploy to both slots. *Evidence: broker running on slot, watcher active.*
- [ ] **D3.2 — Broker consumes GrantHub grants.** Replace static per-user creds with the GrantHub flow: read `/data/sessions/<user>/grant/`, unwrap `K_user`, mint isolated Vaultwarden session (separate state folder, proven pattern), read item via `bw get item` (or direct decrypt). *Evidence: broker log (booleans only).*
- [ ] **D3.3 — OIDC session flow.** SSO auto-login on slots for pmo.city apps: watcher fills tinyauth/IdP redirect (`auth.pmo.city` / `auth.aikumi.app`) via CDP, verifies `.pmo.city` cookie; proactive re-login before 24 h expiry. *Evidence: live session cookie + app tab loads.*
- [ ] **D3.4 — IdP test client (A2b).** Dedicated `cloudbrowser-broker` OIDC client on Authentik + `spike-user` test user. **Admin-side creation** (A2 brief) — reuse the existing cloudbrowser client for smoke until the dedicated client exists; flag for Tigo/admin when the smoke proves the port. *Evidence: client id used.*
- [ ] **D3.5 — Tests + live verification.** Broker port harness + live SSO login + item read on a real slot; no regression (harness green). *Evidence: logs + harness.*
- [ ] **D3.6 — Report + doc updates.** Write D3 result into this doc + deltas row 4 + DoD box; note any A2b external dependency. *Evidence: commit.*

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
