# 26 — S7: Fleet Browser (middle path, v2) — design for decision

> **Status:** v2 = MIDDLE PATH — Tigo decision 2026-08-19: N stock neko
> containers as slots + 1 first-class router service. v1 (single-container
> fleet with embedded manager) superseded — rebuilt 2026-08-19.
> **Companion docs:** `25-d1-orchestration-feasibility.md` (S1/S2/S6 mechanism
> evidence), `22-w2-progress.md`, `23-d15-sso.md`.
> **Reproduction:** `26-s7-fleet-reproduction.md` — full sync runbook
> (stacks, volumes, script↔deployment mapping sha-verified 2026-08-20,
> CfT seeding, rebuild-from-zero steps, verification battery). Router code:
> `scripts/router-v2.py` (deployed from the shared scripts volume).
> **Repos:** internal only (pmo-city-builds). Template mirror deferred until
> the design is approved.

---

## 1. Why this scenario exists

Two facts drove S7:

1. **Per-user Coolify apps (S6 clone model) need a team-scoped API token in
   production.** Coolify 4.3.7 tokens are scoped to the whole team with
   abilities (`read`/`write`/`deploy`); there is **no per-project,
   per-environment or per-server scoping** (verified against the running
   instance's OpenAPI spec; per-project scoping exists only as an upstream
   proposal, May 2026). Creating/cloning/deleting services requires `write`
   → a compromised spawner token = deploy-anything-anywhere = effectively
   root on every server of the team. **Rejected for production.**

2. **A single Coolify application can host many browser sessions.** neko is a
   plain Go process; nothing prevents N instances in one container (N ×
   Xvfb displays, N × neko binds, N × Chrome profiles, N × EPR ranges). All
   the pieces were proven individually in S6 (multi-instance mechanics,
   per-instance EPR, seeding, kiosk parking, SSL procedure).

S7 = **one Coolify service (a "fleet") that owns N personal browser slots**,
with employees as runtime data — not compose paragraphs.

**v2 = middle path (Tigo, 2026-08-19):** the fleet is *not* one container
running N process-sets behind an embedded router. Instead:

- **N slot containers** — each a **stock** `ghcr.io/m1k1o/neko/google-chrome`
  container (stock image, stock env, **stock baked healthcheck — passes
  because neko runs normally on its own `:8080`**), each with its own
  profile volume (identity = employee, immutable).
- **1 router service** — a first-class compose service (its own container,
  own trivial `/health`), the only externally exposed service. Reads
  `remote-user` (tinyauth) → sticky-assigns the employee to a slot → proxies
  HTTP/WS/WebRTC-signaling to `slot-N:8080` (compose DNS).
- **M > N works**: N slots assigned → employee N+1 sees the polite
  "no more browsers available" page (busy page). Slots are **sticky**
  (container = employee's identity), so the busy page is the signal to
  resize the fleet (add slot N+1 = one compose block + redeploy — standard
  Coolify, no token, no runtime provisioning).
- No custom session-manager, no port farming, no supervisord gymnastics:
  the healthcheck-episode class of bugs is eliminated by construction.

## 2. The design in one paragraph

```
                           ┌───────────────────────────────────────────┐
                           │        FLEET SERVICE (one Coolify)        │
  browser.pmo.city ───────▶│  router (first-class service, :8081)     │
      │  (Traefik +        │  │  reads remote-user (tinyauth)          │
      │   tinyauth gate)   │  │  sticky map user→slot (state volume)   │
      │                    │  ▼                                        │
      │                    │  ┌─────────┬─────────┬─────────┐          │
      ├─ WS/HTTP (user A)─▶│  │ slot-1  │ slot-2  │ slot-3  │  ...     │
      │                    │  │ :8080   │ :8080   │ :8080   │          │
      │ WebRTC UDP direct  │  │ neko+   │ neko+   │ neko+   │          │
      │ (per-slot EPR)     │  │ Chrome  │ Chrome  │ Chrome  │          │
      │                    │  │ vol A   │ vol B   │ vol C   │          │
      │                    │  └─────────┴─────────┴─────────┘          │
      │                    │   all stock neko, baked healthcheck OK    │
      └────────────────────┼───────────────────────────────────────────┘
```

- The **router** is the only component with custom code — it replaces the
  fleet v1 manager+router, but as a normal service with a normal healthcheck.
- **Slots are stock neko containers**: nothing custom inside, baked
  healthcheck (`wget localhost:${NEKO_BIND#*:}/health`) passes because neko
  runs normally on `:8080` inside each slot. No image forks, no supervisord
  overrides, no per-slot hacks.
- **Sticky assignment**: first login of an employee → router persists
  `user → slot` in a small state volume; that employee always returns to the
  same slot (their profile, cookies, downloads).
- **Cap**: all N slots assigned → next employee gets the busy page (503)
  until a slot is freed by resize (operator adds a slot block to compose +
  redeploy — standard Coolify flow, no API token).

## 2a. v1 → v2: what changed and why

| | v1 fleet (probe, destroyed) | v2 middle path (live) |
|---|---|---|
| Slot | process-set inside the fleet container (manager-spawned) | **stock neko container** |
| Healthcheck | custom (baked one broke — neko stopped on :8080) | **baked stock** — always passes |
| Router | embedded in viewer image | **first-class service** with own healthcheck |
| Session manager | daemon spawning/killing processes | **gone** — compose owns slot lifecycle |
| Custom code | router + manager + per-slot supervisord confs | **router only** |
| M>N | idle-stop freed slots | **sticky slots**; busy page = resize signal |
| Port farming | 8082+, 9233+, 9400+ inside one container | **none** — each slot owns :8080 internally |

## 3. Data model — employees are runtime data

```
/data/sessions/
  alice@aikumi.pro/   chrome-profile/   downloads/   tabs.json
  bob@aikumi.pro/     chrome-profile/   downloads/   tabs.json
  carol@aikumi.pro/   chrome-profile/   downloads/   tabs.json
```

| Entity | What it is | Created how |
|---|---|---|
| Session dir | the employee's persistent browser (profile, tabs, downloads) | manager API: `POST /sessions {user}` (admin) or first-login auto-create |
| Running session | a process set started by the manager for that dir | manager: `start <user>` (seconds) |
| Slot | one running session's share of the container budget | counted against `MAX_RUNNING_BROWSERS` |

- **Onboarding an employee = creating a directory.** No compose edit, no
  redeploy, no Coolify API, no token.
- **The employee list is not configuration.** Compose stays static:
  one service, one volume, one env block (`MAX_RUNNING_BROWSERS`, screen,
  EPR pool, …).

## 4. Components (in-container, all existing patterns)

| Component | Job | Basis |
|---|---|---|
| Session manager | owns process sets: create/start/stop/list sessions; enforces cap; idle sweep; allocates ports/EPR/displays | new small daemon (~200 lines, same pattern as downloads-api) |
| Router | front door on :8081: reads `remote-user`, maps user → session port, proxies HTTP+WS | extends title-proxy (already reads Remote-Email) |
| neko × N | per-session streaming UI + WebRTC | existing image, per-session process |
| Xvfb × N | per-session display | existing x-server conf, per-display |
| Chrome × N | per-session kiosk browser (CfT 128 pinned, tabbar ext, kiosk flags) | existing google-chrome.conf, per-profile |
| sso-broker × N | per-session tinyauth/Authentik autofill on session expiry | existing sso-broker.py, per-session instance |
| downloads-api | serves each session's downloads dir (quota 5 GB / 90 d, ClamAV) | existing, session-aware path |
| janitor | retention/quota sweep across session dirs | existing |

Port/display/EPR allocation (per-session, allocated by the manager from
pools; **no host port bindings** — all inside the container):

| Pool | Range (pilot) |
|---|---|
| neko HTTP | 8082 + i |
| CDP relay | 9233 + i |
| Xvfb display | :99 + i |
| EPR (UDP, per session) | 52200 + 100·i … +99 |

## 5. Lifecycle flows

**First login (employee never seen):**
`user → browser.pmo.city → tinyauth gate (group) → router → remote-user` →
manager: no session dir → create + start (profile seed, ~30 s) → proxy in.
Controlled by `AUTO_CREATE_SESSIONS` (pilot `false` → pre-created test users;
production `true`). Auto-create needs (small, all easy):
- identity → dir-name sanitization (`alice@aikumi.pro` → `alice-at-aikumi.pro`)
- a "we are preparing your browser" first-login page (~30 s)
- janitor rule: delete session dirs never used after N days (storage policy)
- optional denylist for group members who should not get a browser (admins, service accounts)

**Return visit (session exists, stopped):**
router → manager: dir exists but stopped → start (Chrome+neko, seconds) →
proxy in. Tabs/downloads come back from the dir (D5 snapshot in `tabs.json`
**moved into the session dir** — the S3 risk item is solved here).

**Active use:** user streamed; agent (Hermes) drives the session's Chrome
via its CDP relay when the user grants control (existing W1/W2 path).

**Idle:** no neko viewer connected for N minutes → manager stops the
process set, keeps the dir, frees the slot.

**Cap reached (`MAX_RUNNING_BROWSERS` running):** router → polite
"all browsers are busy, try again in a moment" page. Optional refinement:
evict the longest-idle session instead of refusing (decision D-S7-3).

**Container restart:** supervisord boots router + manager; manager
restores running sessions from a state file (`sessions.json` in the
volume); profiles are untouched.

## 6. Auth model — group gate + user-level routing

- tinyauth keeps its job: one app-key, `config.domain=browser.pmo.city`,
  `oauth.groups=<team group>` — it answers **"is this an authenticated
  employee?"**.
- The router answers **"which browser?"** from the `remote-user` header
  tinyauth injects per request (already proven live: the title bar shows
  the logged-in email).
- **Result: user-level isolation, which the current per-user-app model does
  NOT have** (today any group member can open the shared viewer; per-user
  apps were still group-gated, not user-gated).
- **Header trust (security requirement):** a client could send a forged
  `remote-user`. tinyauth's middleware *appends* its headers to the request;
  the router must (a) only be reachable behind Traefik+tinyauth (401 gate)
  and (b) read the **last** occurrence of the header (tinyauth's), or the
  edge strips client-supplied duplicates. To be validated in the probe.

## 7. Capacity & resources (from W1/S6 measurements)

- Idle session ≈ 431 MiB + Chrome ≈ 0.5 GB; software encoding ≈ 1 core per
  session at 1920×1080@30 → **slots ≈ (cores ÷ 1, RAM ÷ 2 GB)**.
- Container mem limit = slots × ~2 GB (e.g. 4 slots → 8 GB cap).
- `MAX_RUNNING_BROWSERS` = the pilot's slot count (default 4, decision
  D-S7-2).
- EPR ranges are per-session *inside one container*: only non-overlap
  matters, no host-port conflicts (simpler than S6's cross-container case).

## 8. Security notes

- **No Coolify API token anywhere in the runtime** — session ops are
  process ops. Token only ever used by a human/admin for one-shot fleet
  provisioning (clone the base service).
- Secrets (broker creds) stay in the existing 0600 base64 file, never in
  logs/LLM context (locked decision G).
- Container compromise = all sessions of that fleet (inherent to
  shared-container; per-team fleets bound the blast radius — decision
  D-S7-4).
- Chrome crash = that session only (supervised); container crash = all
  sessions (same as today's single viewer).

## 8b. Vocabulary: Tenant / Fleet / Group

| Term | Meaning | Example |
|---|---|---|
| **Tenant** | an organization that receives the product | Groupe Alsei = 1 tenant |
| **Fleet** | one Coolify app = one container with S session slots | `cb-fleet-<uuid>`, domain `browser.pmo.city` |
| **Group** | tinyauth auth group = who may enter a fleet's domain | `alsei-employees`, `crmoc-team`, … |

- **Naming convention (all clones):** `cb-<flavor>-<uuid>` — e.g.
  `cb-probe-s6-<uuid>`, `cb-fleet-<uuid>` — the pre-fix makes a service's
  type visible in the Coolify service list without opening it; the uuid
  suffix keeps names unique across clones (never reuse a name).
- A fleet is a **capacity unit** (S slots from cores ÷ 1, RAM ÷ 2 GB), not an
  org unit. Employees ≠ running sessions: sessions idle-stop and free slots.
- **Sizing:** slots needed ≈ employees × peak-concurrency%. 40 employees at
  15–20 % peak ≈ 6–8 slots → 1 fleet on an 8-core/16 GB host (pilot data
  refines this). Headcount drives **storage** (40 × 5 GB downloads ≈ 200 GB),
  not fleet count.
- **More fleets for exactly two reasons:** (1) capacity overflow
  (concurrency > one container) → fleet #2… each with its own Coolify app +
  domain; (2) governance/isolation (BU separation, blast radius) → one fleet
  + one tinyauth group per BU (`crmoc-team` → `browser-crmoc.pmo.city`).
- Default for a 40-person tenant: **1 tenant, 1 group (all employees),
  1 fleet**; per-BU fleets are an option the company can take later.

## 8c. Agent roles — standard vs admin

Two agent principals exist in the control plane (the channel that drives
browsers — CDP/MCP, spec H), mirroring the human roles:

| Role | Who | Can do |
|---|---|---|
| **Standard agent** | the employee's own agent (1:1 with its browser) | drive ONLY its own session: navigate, type, extract, download. **Cannot list or inspect other sessions** — no other users' profiles, tabs, downloads, or URLs. |
| **Admin agent** | fleet operator / support (human-approved) | list all sessions, read fleet state, stop/start any session, view downloads metadata for support. Never sees credential material (broker rule, D15). |

- The boundary lives in the session-manager API — the only surface that can
  enumerate sessions: standard-agent tokens are scoped to
  `/sessions/<own-user>/*`; `/sessions` (list) and `/sessions/<other>/*`
  require the admin role. Router and CDP stay per-session by construction.
- **Documented notion for the pilot**; enforcement lands with the agent
  control plane (full MCP control, spec H). Until then the session-manager
  API is loopback-only and the boundary is physical.

## 9. What carries over unchanged (already proven)

- S6 clone recipe to create the fleet base service (incl. SSL
  start-stop-start, ID-suffix naming, `connect_to_docker_network`).
- Fresh-volume seeding (scripts mirror + CfT binary + chown 1000:1000).
- Kiosk parking (close app-root tabs → downloads page) + window-bounds fix.
- D8 downloads UX, D9 capacity caps, D11 CfT pin, D12 hygiene, D15 broker
  (per-session), tabbar/branding/title-proxy.

## 10. Prototype (S7 probe) — what gets built & verified

**Build (dev01, on a clone of the current viewer; live viewer untouched):**
1. Clone `cloudbrowser-4guplgcrvug7l7h64m2cxkm1` → fleet base
   `cb-fleet-<uuid>` — name MUST be pre-fixed per §8b (S6 recipe, domain
   `s7fleet.dev01.pmo.city`).
2. Add session manager + router (python, supervisord-managed).
3. Seed two test sessions (`spike-user`, one second test user).

**Verify:**
- Two sessions running simultaneously (2× neko/Xvfb/Chrome/broker), each
  isolated (profiles, downloads, tabs).
- Router: `remote-user` → correct session; forged-header test (see §6b).
- Session stop (idle) while the other keeps running; start → state back.
- Cap: 2/2 running → third user gets the "busy" page.
- Container restart → running sessions restored from `sessions.json`.
- SSO broker still lands (per-session), downloads + quota work per session.

**Teardown:** DELETE the fleet clone (same API pattern as S6 probe).

## 10b. S7 probe results (2026-08-19) — built, verified live, ONE external gate

**All in-container mechanics verified E2E** (see probe ledger for detail):
routing (remote-user → per-user neko/EPR/files), forged-header last-wins,
cap 2/2 → busy page, per-session isolation (profiles, downloads), hard-kill
→ boot restore, idle stop (35s) → stays stopped, clean manager restart.

**Bugs found & fixed (all in the fleet sources, `/opt/data/fleet-src/`):**
1. Port collisions → disjoint per-session ranges.
2. Relay ↔ Chrome same-port bind → separate relay base.
3. Stale `/tmp/.X99-lock` after killed Xorg → pid-alive pre-clean.
4. Idle-sweep vs crash-monitor restart loop → `stopping`/`_restarting` guards.
5. Orphaned processes on manager restart → SIGTERM handler + boot orphan sweep.
6. Concurrent start/stop races → per-session locks.
7. JSON-serializable session state (lock objects) → `_public()`.
8. **Router WS relay never fired**: `if "upgrade" in ...` tested the literal
   substring "upgrade" against the header VALUE ("websocket") — always
   False → every WS request fell into the plain-HTTP urllib path → 502.
   Fixed: `if "websocket" in upg.lower()`.
9. **Router WS relay client→server direction crashed**: `pump(rfile, sock)`
   called `.recv` on a `BufferedReader` (no such attr) → neko's auth channel
   dead. Fixed: drain rfile via `peek`/`read`, then raw-socket pumps both ways.

**External gate — THE blocker Tigo diagnosed (healthcheck):** the fleet
manager stops the image's own neko (`:8080`), so the *baked* image
healthcheck (`wget localhost:${NEKO_BIND#*:}/health`) always fails →
container flips `unhealthy` → **Coolify's Traefik stops routing to it** →
all requests hit the catch-all (`https://www.on-ai.sbs/error.html`), even
though labels/network/service were all correct. This is why the domain
looked dead while the app was fully up.
- Fix: `healthcheck:` on **every service of the stack** (Tigo's call — a
  broken container anywhere flips the whole service `unhealthy`): viewer
  pings the router's `/health` (endpoint added to the router); browser
  pings CDP `:9222/json/version`; fake-login GETs `:8080`; janitor checks
  `/proc/1/cmdline`; clamav runs the image's `clamdcheck.sh`. All five
  containers `(healthy)`, service `running:healthy`, gate live:
  `s7fleet.dev01.pmo.city` → 302 → `auth.pmo.city/login?login_for=app&redirect_uri=…`
  (401 only for non-browser Accept headers — tinyauth v5 normal behavior).
- Coolify lesson: **a container without a passing healthcheck is invisible
  to the proxy** — every future fleet/per-session component must keep the
  checked endpoint alive (or override the healthcheck).

**Open:** the probe stays RUNNING for Tigo's UI check (SSO as a PMOC user,
then a second user for isolation); teardown on his word.
→ **2026-08-19: RESOLVED — middle path approved; v1 fleet torn down and
rebuilt as v2 (stock slots + router service).**

### v2 rebuild — live evidence (2026-08-19)

Service `cb-fleet-v2` (`okixw2fxnwn1lakxvxajodww`), created via API
(`POST /services` with `docker_compose_raw` + `urls` — needed
`destination_uuid` `y7ugdp7gi1tip6uwpjzp76ea` = pmoc-lan, destination id 8;
a 400 without it). Domain re-attached on the router app
(`https://s7fleet.dev01.pmo.city:8081`).

- **5 containers, all `running:healthy` with STOCK baked healthchecks** —
  slots run neko normally on their own `:8080`; zero healthcheck overrides
  (v1's blocker class eliminated by construction).
- **Router is a first-class service** (`python:3.12-slim`, `/health` on
  :8081, raw-socket TCP proxy → WS upgrade works; state volume for the
  sticky map). One mount pitfall found & fixed during build: a read-only
  `/data` mount cannot host a nested writable `/data/state` — mount
  scripts at `/app:ro`, state at `/data/state` (separate paths).
- **Sticky assignment live:** `spike-user@aikumi.pro → slot-1`,
  `montigaud@aikumi.pro → slot-2` (persisted in
  `router-state/router-state.json`).
- **M>N busy page verified:** 3rd user (direct router test) → 503
  "All browsers are busy".
- **E2E SSO chain verified headless:** `s7fleet.dev01.pmo.city` → 302 →
  Aikumi Connect (`auth.pmo.city`, shadow-DOM Authentik fill — same
  technique as the W1 sso-broker: `ak-flow-executor` >
  `ak-stage-identification` > `uidField`/`password`; creds
  spike-user/FAKE_LOGIN_PASS) → consent → back to fleet → **neko UI
  renders through the router** (`/js/*`, `/ws?password=neko` proxied to
  the right slot). neko password gate (second gate) unchanged.
- **Footprint:** router ~20 MiB, slots 0.2–0.5 GiB each (neko+Chrome),
  clamav ~0.95 GiB. mem_limit 2g + shm 2gb per slot.
- WebRTC media plane: headless test browser crashed on video connect
  (no GPU in headless); real-browser check pending Tigo.
  → **2026-08-19 (later): Tigo confirmed VIDEO WORKS in his real browser.** ✅

### v2 customization pass — branding + tabbar + email (2026-08-19, approved A+B)

- **Service renamed** via API (localhost route): `cb-fleet-v2` →
  `cb-fleet-v2-okixw2fxnwn1lakxvxajodww` (matches container suffix convention).
- **Scope B applied** (branding + tabbar + title-proxy; NO downloads-api yet):
  scripts volume now carries `branding/` + `branding-init`, `tabbar-extension/`,
  `google-chrome.conf` (slot variant, `26-s7-fleet-slot-chrome.conf`), and
  `title-proxy.py/.conf`; slots mount `scripts:/etc/neko/supervisord:ro`
  (supervisord include dir → auto-loads the .conf programs; the image's own
  x-server/neko programs stay in the top-level supervisord.conf). The slot
  chrome.conf runs Chrome for Testing 128 via the `slot-prepare-chrome.sh`
  wrapper (kiosk + CDP, see "Real-case CDP" below) + re-declares the openbox
  program (the stock file it lived in is hidden by the mount).
- **Chain:** router (sticky, raw-TCP proxy, forwards ALL headers incl.
  Remote-Email) → `slot-N:8081` title-proxy (rewrites `<title>` to
  "Cloudbrowser: <email>", injects top-bar `🔒 Secrets` + `📁 Files` +
  email chip, relays WS) → neko `:8080`. Router targets 8081 via new
  `SLOT_PORT` env (default 8080).
- **Verified live:** all 5 containers healthy; slot title-proxy returns
  `<title>Cloudbrowser: test@aikumi.pro</title>` + cb-email/cb-tool-files/
  cb-tool-vw; branding applied (`logo.800bec71.svg`, `app.909074c1.js` in
  /var/www); tabbar flags on the chrome process
  (`--load-extension` + `--disable-extensions-except`); router → slot:8081
  works for assigned users; 3rd user still gets the 503 busy page.
- **Dead button (known, W2):** tabbar "relaunch" targets
  `http://127.0.0.1:9230/restart` (restart-api) which is NOT deployed per
  scope B → relaunch button errors until restart-api ships with downloads.
- **CDP probe (2026-08-20) — stock Chrome 133 confirmed CDP-broken, CfT
  required for agent control.** Tigo asked to verify whether per-slot agent
  control needs Chrome-for-Testing. Ran `scripts/cdp-probe.py` (pure-stdlib
  CDP client: masked WS frames, event-skipping reader) against three
  targets:
  - CfT 128 viewer (control): **all 5 steps PASS** — page-WS evaluate
    `1+1`→2, attachToTarget→sessionId, session-scoped evaluate→title.
  - Stock 133 slot (full config): page-WS **closes instantly**,
    attachToTarget **kills the browser WS**.
  - Stock 133 bare (clean profile, no extensions, no kiosk flags, port
    9224): page-WS **TIMEOUT 8 s** (the W1 hang) and session evaluate
    **`-32001 Session with given id not found`** — W1 reproduced verbatim.
  → It is the Chrome **build**, not our config: any per-slot agent control
  (FR-4) will require pinning CfT on the slots (same swap as the viewer:
  binary in profile volume + flags). Probe kept in repo for W2 re-runs;
  slot conf reverted to no-CDP-flags committed state after the test.
- **Ops finding:** Coolify prod API key now rejects the gateway's egress IP
  ("You are not allowed to access the API" on ALL endpoints incl. reads —
  worked earlier the same day); the SAME token works from mother01 localhost
  (`http://localhost:8000/api/v1`). Workaround: `scripts/coolify-local.sh`
  (SSH → localhost curl). **TODO for Tigo:** re-check the key's allowed-IPs
  in Coolify UI, or the gateway loses API access permanently.
- **Real-case CDP (2026-08-20, Tigo go) — slots are now agent-controllable,
  humans unchanged.** The whole point of the product is an agent-controllable
  browser, so CDP was activated now rather than waiting for the W2 FR-4
  milestone:
  - **CfT 128.0.6613.137** seeded into each slot's profile volume at
    `/home/neko/.config/cft-chrome-128/` (copied from the viewer's verified
    install; chown 1000:1000). Stock Chrome 133 stays in the image but is no
    longer launched (CDP-broken, see probe above).
  - **`slot-prepare-chrome.sh`** wrapper (mirrors the viewer's
    `prepare-chrome.sh`): Singleton-lock cleanup → Preferences patch
    (restore_on_startup=5 fresh start, translate off) → exec CfT with
    `--kiosk --disable-infobars --window-size=1920,1080` (the "Chrome for
    Testing" notice bar does not render in kiosk — verified in
    screenshot; explicit window size = kiosk geometry insurance, see
    sizing note below), CDP
    `--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0
    --remote-allow-origins='*'`, tabbar extension, start URL
    **https://pmo.city** (product homepage per Tigo; tabbar verified to
    render there too, so no need for the Cloud Files boot URL).
  - **`cdp-relay`** (existing `cdp-relay.py`, same as viewer) added to the
    slot conf: exposes `0.0.0.0:9223 → 127.0.0.1:9222` for external agent
    access (CfT builds WS URLs from the request Host header, so the relay is
    a pure TCP pipe).
  - **Agent access path:** CDP is reachable the way agent frameworks expect —
    the cdp-relay binds **0.0.0.0:9223 on the PMO-LAN** (no SSH tunnel
    required): any agent on pmoc-lan points its browser-use / MCP / CDP
    client at `ws://<slot-ip>:9223` (e.g. `ws://10.0.34.5:9223`). Verified:
    `cdp-probe.py` all 5 steps PASS from the mother01 host (not inside the
    container) against both `10.0.34.5:9223` and `10.0.34.6:9223` with no
    tunnel — this is exactly the surface browser-use consumes. The SSH tunnel
    I mentioned earlier is only a dev convenience from outside the LAN; the
    production path is pmoc-lan direct (this is why the resources live on
    PMO-LAN).
  - **Human path verified unchanged:** screenshot shows kiosk (no native
    strip), tabbar present, NO CfT/flag banner; router:8081 (ROUTER_PORT)
    still sticky-routes spike-user→slot-1 / montigaud→slot-2 with
    title-proxy titles + toolbar; external `s7fleet.dev01.pmo.city` → HTTP
    401 (tinyauth gate, correct).
  - Slot IPs (pmoc-lan net): router 10.0.34.2, slot-1 10.0.34.5, slot-2
    10.0.34.6.
- **restart-api deployed on the slots (2026-08-20) — Relaunch button now
  works.** The tabbar's "Relaunch Chrome" POSTs `http://127.0.0.1:9230/restart`;
  each slot now runs restart-api (same code as the viewer, PROFILE_DIR
  env → `/home/neko/.config/google-chrome` slot variant): POST /restart
  does `supervisorctl restart google-chrome` (verified live: `ok:true,
  chrome stopped→started, cdp_ok:True` after 12 s), plus the CDP watchdog
  (self-heal) and D5 tab snapshot/restore. The earlier "dead button"
  finding is resolved.
- **W2 deltas unchanged:** `/files` downloads surface (downloads-api +
  cloudfiles route), idle-stop refinement. (Per-slot CDP is now DONE — the
  CfT decision landed with this change.)

**Known deltas to close in W2:**
1. `/files` downloads surface (FR-12) — v2 router forwards everything to
   slot `:8080`; per-slot downloads-api needed (janitor already scans
   per-slot roots: `DOWNLOADS=/data/downloads/slot-1,/data/downloads/slot-2`).
4. **Kiosk window sizing (2026-08-21):** `--restore-last-session` +
   `restore_on_startup=1` restored the previous session's window geometry
   (945×1060 on 1920×1080 → small window + black void). Fixed in the
   wrapper: `--window-size=1920,1080` + `restore_on_startup=5`, **staged
   (repo + scripts volume), applies at next natural Chrome restart.**
   Pilot workaround meanwhile: tabbar **Relaunch Chrome** restore button
   reloads at the right size — users should know this.
2. Agent control (FR-4) per slot: stock slots don't expose CDP — a
   chrome.conf override (supervisord include) per slot, or a per-slot
   CDP relay, as the viewer does.
3. Idle-stop per slot (RAM) — slots are always-on by design; a stop
   policy (scale down / hibernate) is a refinement, not a blocker.

- **Spec 27 — tabbar v1.5.0 rollout (2026-08-21, DONE & verified).** Home
  \U0001F3E0 + Plus \u2795 icons, inline URL popover, tab limit
  (`TAB_LIMIT`, default 3 — Home/Plus grayed with tooltip at limit),
  homepage opens **only when zero real tabs** (launch URL removed from
  `slot-prepare-chrome.sh`; restart-api `ensure_homepage()` covers boot,
  Relaunch, watchdog), D5 restore **capped at `TAB_LIMIT`**. restart-api
  gains `GET /config` \u2192 `{homeUrl, tabLimit}` (MV3 can't read env; the
  extension fetches at startup, falls back to defaults). `HOME_URL` +
  `TAB_LIMIT` added to fleet + viewer compose raw and Coolify env tables
  (raw, no literal quoting) — effective at the next redeploy; running
  containers use the built-in defaults. Internal `98076e4`, template
  mirror `7674178` (placeholders). Verified live on slot-1, slot-2 and the
  viewer: exactly one pmo.city tab per slot after a clean restore pass;
  Home/Plus click-tested via CDP; limit gray-out confirmed at 5 tabs
  (`home.disabled`/`plus.disabled` true, tooltip "Tab limit reached (3)");
  `EXT_VERSION === "1.5.0"` on all three. Full record in
  `27-tabbar-home-limit.md` (Implementation record).
  **Pitfalls (documented for future deploys):** (a) Chrome caches the MV3
  service-worker script per-profile in `$PROFILE/Default/Service
  Worker/ScriptCache` — after updating `background.js`, stop Chrome, clear
  that dir (the root `Service Worker/` is vestigial), start; otherwise the
  SW silently runs old code (manifest says new version). (b) A manual
  `supervisorctl stop/start google-chrome` does NOT trigger tab restore —
  the browser parks at newtab; use `POST /restart` for planned restarts.

- **Spec 27 S6 — LRU eviction replaces the limit block (2026-08-21, DONE &
  verified).** At `TAB_LIMIT` Home/Plus stay enabled; the background worker
  closes the least-recently-used real tab (`lastAccessed`, active tab never
  evicted) before opening the new one; a 4.5 s toast on the submitting tab
  names the closed tab (response-carried title — no race with the new
  tab's load). tabbar-extension v1.6.0 (manifest + EXT_VERSION + VERSION in
  lockstep). Verified live on slot-2: LRU victim correct across two
  activation patterns, toast + tooltips confirmed, still 3 tabs after each
  open; `EXT_VERSION === "1.6.0"` on all three containers. Full record in
  `27-tabbar-home-limit.md` (S6 section). Ledger W3 (watchdog-restore
  gap: Chrome self-exit + supervisord auto-restart skips tab restore,
  parks at newtab) — **FIXED 2026-08-21 with Tigo approval**: watchdog
  queues restore on ANY Chrome main-PID change (supervisord auto-restart,
  manual start, crash loop), no-op when tabs present; verified live on
  slot-2 (SIGKILL → pid change → auto-restore → pmo.city back, no
  `POST /restart`).

- 2026-08-19 (Tigo): `AUTO_CREATE_SESSIONS=true` — a first login
  auto-creates the employee's session (no manual seeding). Verified E2E:
  unknown user via router → session created + started (200), then cleaned
  up. The "all browsers busy" page now only appears at the real cap
  (2/2 running).
- 2026-08-19 (Tigo): agent roles notion recorded (see §8c) — standard
  agent cannot list other sessions; admin agent can. Enforcement lands
  with the control plane (spec H).

- **Spec 29 — idle suspend/resume (2026-08-21, DONE & verified).** Fleet
  slots now release idle sessions instead of holding them forever:
  reaper in `restart-api.py` (activity sources `xinput,media,tabs,cdp` —
  X11 idle, WebRTC peer, tab-set diffs, CDP relay timestamps), grace
  countdown toast (tabbar v1.8.0), suspend = stop Chrome → archive
  profile (minus caches) + Downloads to `sessions:/data/sessions/<user>`
  → wipe slot profile → router `/fleet/release`; resume = router archive
  wake on the first free slot → restore → Chrome start → tabs back.
  Compose: `sessions` volume on both slots + 5 `IDLE_*` vars (defaults
  15/5/60, live test values 2/1/10); viewer pinned `IDLE_ACTION=none`.
  Router 29b identity sweep (`IDENTIFY_SWEEP_INTERVAL=30`) re-pushes
  `{user, slot}` so a slot always knows who to archive (kills the
  stuck-slot mode). **Two post-deploy bugs found during the soak and
  fixed** (full record `29-idle-suspend-resume.md` §10–11):
  (a) IPv6-mapped loopback (`::ffff:127.0.0.1`) was counted as a viewer →
  media source never idle → reaper blind; (b) suspend left title-proxy
  holding the neko member WS → neko kept encoding ~1 core — suspend now
  also stops title-proxy, wake restarts it, `/identify` repairs it.
  E2E: slot-2 full cycle (identify → idle → grace → suspend → archive
  194M → wipe → release → wake → 3 tabs back). Commits: scripts
  `restart-api.py` md5 `d6b7d6a8` (spec 31 fresh wake, sha256 `e2222649…`),
  `router-v2.py` `f6545e12` (spec 31 v3, sha256 `24d24f52…`),
  `cdp-relay.py` `83812991`, tabbar content.js `87bedac9` (all
  repo == deployed, verified 2026-08-21).
  **Open (mandate, not blocker):** healthchecks on fleet slots + viewer
  stack (see spec 29 §11).

## 11. Decisions needed from Tigo

| # | Question | Working assumption |
|---|---|---|
| D-S7-1 | Personal browser per employee (router, not pool)? | **Yes — personal, immutable, never expires** (locked earlier; confirmed for S7 v2) |
| D-S7-2 | Pilot slot count (N slot containers) | 2 (Tigo + one tester); M>N → busy page = resize signal |
| D-S7-3 | Cap reached: refuse vs idle-evict | Refuse politely (busy page); slots are sticky — eviction = resize |
| D-S7-4 | Fleet topology: one fleet per tenant (default) vs per-BU fleets (governance) | 1 tenant = 1 fleet, sized by headcount; per-BU fleets only if the company wants isolation |
| D-S7-5 | Session creation mode | **Resolved by v2**: auto-create = router sticky-assigns first login to a free slot (`AUTO_CREATE_SESSIONS=true`); no per-employee compose edits at runtime |
| D-S7-6 | Fate of the current shared viewer (`cloudbrowser.dev01.pmo.city`) | Stays as admin/shared browser during W2; fleet replaces it at MVP |

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Shared container = single point of failure | Same as today; supervisord + restart-api + startretries; per-team fleets |
| Multi-neko in one container unproven | S7 probe is exactly this test; fallback = per-user apps (S6, dev-only token) |
| remote-user spoofing | Edge stripping + last-header-wins (validated in probe) |
| Resource contention (one session eats the budget) | per-session cgroup-less soft caps; manager enforces; slots sized from W1 data |
| neko UI/WebRTC quirks with N instances on one IP | ICELITE + per-session EPR pools; S4-style check folded into probe |
