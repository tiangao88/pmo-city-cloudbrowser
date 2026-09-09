# CloudBrowser v2 — Durable Plan (status as of 2026-09-08)

Repo: `https://github.com/tiangao88/pmo-city-cloudbrowser` (branch `main`).
Dev-staging fleet: Coolify service `nievufka0cggf82cregyihav` (instance
`cloudbrowser2-dev-v01`), hosts `cloudbrowser2.dev01.pmo.city` (viewer) and
`cloudfiles2.dev01.pmo.city` (CloudFiles). Phase 6 production rollout remains
separately gated.

This file is the single durable plan. It lives in the repo so it survives
workspace wipes. Update it at the end of every milestone.

## Where we are

All CloudFiles phases 0–5 are implemented, gated, and pushed. The router
control plane (session create/activate, slot wake, agent forwarding, lease
rotation) is implemented and verified live on dev-staging.

**Milestone 1 (viewer UI + interactive surface) is implemented, gated, and
deployed to dev01.** The public viewer page at `cloudbrowser2.dev01.pmo.city`
is no longer a static placeholder: after edge SSO it auto-joins the router
queue (`POST /ui/session/join`), polls session state (`GET /ui/session`),
activates an offered session (`POST /ui/session/activate`), and once active
drives the assigned slot through the router's allowlisted agent operations
(`POST /ui/agent/<op>`: navigate/click/type/page_info/tabs_list) — all with
the same fail-closed identity rules and bounded envelopes as the rest of the
control plane. The real router client (`RouterHttpClient`) carries the agent
relay; wire-level tests pin the exact path/method/headers/body it sends.

Live fleet is healthy on the `2416673` build (digest sync `d693101`).

Milestone 1 **confirmed by Tigo's public-host retest on 2026-09-08** (active
session with countdown, navigate/page_info working, roster showing who holds
the slot vs who is waiting, leave/release working). Closed.

**Fixes shipped 2026-09-08 (`ffda61c`, decision by Tigo):**

- **Self-healing wake takeover** — a slot left running by an ended session
  (expired/abandoned runtime holding a foreign binding) no longer wedges
  the next wake with `operation_failed`. `SlotSupervisor.adopt_binding`
  force-stops the stale browser, then adopts the new server-minted
  binding; `browser_id` guard and stop-failure fail-closed semantics are
  unchanged, and the binding push still happens only while stopped. The
  dev01 q-4/q-6 wedge class is closed (no manual container restarts).
- **Real CDP page actions** — `CdpPageActionAdapter` wires `navigate` and
  `page_info` through the local DevTools endpoint (`Page.navigate` on the
  live page target, `/json/new` only when no page exists; bounded
  `Runtime.evaluate` capture over a short-lived WebSocket). Wired into
  `build_browser_service`; `click`/`type` remain fail-closed until an
  approved element-interaction channel exists; no generic CDP passthrough.

## Shipped (commits on origin/main)

- Phase 0 boundary + red security suite — `f3cc3b4`
- Phase 1 domain + gateway boundary — `a80dfc2`
- Phase 2 downloads ingest + durable storage — `1ac90068`
- Phases 3–5 gateway, phase-4 operational wiring (retention 90d, ClamAV,
  quarantine, erasure), ingest transport — through `8044410`
- Router durable session store — `6c7d812`; control API — `3ab2c6c`
- Activation-driven slots (boot-stopped browser, lease rotation) —
  `56bd70b`…`164a2bf`, `40c1faa`, `00836a3`
- Router queue promotion fix — `40fb03d`
- Viewer authenticated session surface (backend routes) — `d1ca5cf`
- Image digest syncs — `8f7bf19`, `6f63594`, `df2dedc`, `149519a`, `50c0dca`,
  `565dd5c`, `d693101`
- Viewer UI shell: auto-join, status poll, activation, allowlisted agent
  relay — `f313fc3`; real-client agent relay wire fix — `2416673`
- Self-healing wake takeover + real CDP page actions (navigate, page_info)
  — `ffda61c`
- Image digest sync to `2c6a6e7` build (run `34219815337`) — `fee0119`
- Viewer: logged-in display name (`Remote-Name` only, never an identity key)
  + "Leave & release slot" route and button (waiting and active) — `949faea`
- Roster: who is waiting / who holds a slot — `GET /v1/roster` (identity-gated),
  `GET /ui/roster` relay, and a live roster list in the viewer shell;
  display identity switched from `Remote-Name` to the edge-validated
  `Remote-Email` (non-authoritative metadata only, never an identity key)
  — `fd3985b`, digests run `34246186158` (`6680a4a`)
- Roster live on dev01: router `dbdeeb4b…`, viewer `dfa599f7…` swapped via
  compose image-line edit + `up -d --no-deps` (backup kept on host);
  `/v1/roster`, `/ui/roster`, shell wiring, and `display_email` verified
  through in-container probes with real identity headers
- Image digest sync to `949faea` build (run `34231460028`); viewer live on
  dev01 at digest `2968da87…` — `e4740e9`

## Next milestones (dependency order)

1. ~~Viewer frontend + interactive surface~~ — **DONE, confirmed 2026-09-08.**
2. ~~Spec alignment (was plan §3.6)~~ — **DONE 2026-09-08.** Router surface
   (`/v1/session` GET+POST, `/v1/session/activate`, `/v1/session/leave`,
   `/v1/roster`, `/v1/agent/{operation}`) added to
   `specs/contracts/control-api/v1/openapi.yaml` with bounded schemas
   (`SessionResponse`, `RosterResponse`, `AgentActionRequest/Response`,
   `BoundedEnvelope`); yaml parse-verified. Spec 91 status refreshed
   ("delivered through Phase 5"). Gate:
   `tests/contract/test_control_api_contract.py`.
3. ~~Session-TTL product decision~~ — **RESOLVED 2026-09-08: sliding TTL
   wired** (approved in the 2026-09-08 task list). New
   `RouterSessionStore.renew(principal_id)` extends an ACTIVE lease to
   `now + session_ttl_s`; the router calls it best-effort after every
   successfully relayed agent page action (work renews; status polling
   never does; expiry is never resurrected). Renewed expiry survives
   restart via persisted state. Gate:
   `tests/contract/test_router_sessions_sliding_ttl.py`.
4. **Live hygiene (dev01 only, separate approval each)** — cosmetic
   first-activate `supervisor_unavailable` race (wake succeeds; bounded retry
   is the current workaround; candidate for a spec note). ~~Stale static
   binding envs~~ **DELETED from the dev01 Coolify env store 2026-09-08**
   (`CB_PRINCIPAL_ID`/`CB_PROFILE_ID`/`CB_BROWSER_ID`/
   `CB_BINDING_GENERATION`; running containers were untouched — no
   redeploy — and wake uses supervisor binding pushes, so dev01 keeps
   working; the next approved re-render picks up the compose fallbacks
   `browser-slot-1`/`principal-unassigned`/`generation-0`). ~~`broker-state`
   volume orphaned~~ **STALE NOTE, corrected 2026-09-08**: credential-broker
   runs and mounts `nievufka0cggf82cregyihav_broker-state` (verified via
   `docker inspect`).
## Overall roadmap (corrected 2026-09-08 — full refactor scope, not just CloudFiles)

The v0.2 refactor (spec 85–94) covers the whole product: credential broker,
browser platform, CloudFiles, and the W3/W4 packages carried over from the
v1 fleet. CloudFiles phases 0–5 were ONE slice of it. This section is the
single authoritative view of done vs open.

### Done (implemented, gated, pushed; live on dev01)

- Generic Credential Broker per PRD 85 (replaces v1 `sso-broker.py`):
  `src/cloudbrowser/credential_broker/` with authentik / generic_form /
  http_basic / mfa adapters; broker service + compose wiring.
- CloudFiles phases 0–5 (spec 89–94): identity-adapter gateway, ingest,
  quarantine, retention, GDPR erasure, ClamAV scan-before-publish, metrics,
  image qualification, release provenance.
- Router control plane: `/v1/session` lifecycle (create/activate/leave),
  roster, allowlisted agent relay (navigate/click/type/page_info/tabs_list),
  sliding session TTL (work renews, polling does not).
- Viewer shell with interactive relay surface (milestone 1, confirmed by
  Tigo retest 2026-09-08), display names, leave/release.
- Activation-driven slots: boot-stopped Chrome, binding rotation,
  owner-bound lifecycle; durable session state across restarts.
- OpenAPI alignment for the shipped router surface (spec gate green, 701
  tests).

- W3-1 broker login E2E proof — STARTING 2026-09-08 (Tigo approved).
  Plan: `specs/proposals/v0.2/95-w3-1-broker-login-e2e.md`.

### Open — W3 packages carried over (register: `roadmap-w3-status.md`)

- **W3-1 — broker login E2E proof — LAYERS 1-4 SHIPPED (form adapter).**
  Commits: `1d9c17c` (crypto), `25d02e7` (vault client), `72f536e`
  (runtime wiring), `f8ca15f` (form adapter E2E). Gate: `make check` →
  **731 passed**; all validators PASS; `git diff --check` clean.
  What is proven: Hermes intent → broker → per-call Vaultwarden unlock
  (prelogin→grant→sync→decrypt) → SidecarFormBrowser (narrow FormBrowser
  over HttpAgentBrowser) → FormLoginAdapter → broker returns
  `authenticated` to the caller; no material in any response body; the
  adapter cannot navigate or list pages (protocol is the boundary).
  Fail-closed on unreachable sidecar and wrong success selector.

  **Still to land for W3-1 close:** basic (HTTP Basic Auth) and sso
  (Authentik pmoc-sso) adapters. Same shape: vault producer is shared,
  the adapter selector dispatches by `site_id`/`origin` to
  `BasicAuthAdapter.execute` or `SSOAdapter.execute` (both exist in
  `src/cloudbrowser/credential_broker/adapters/`), each with its own
  test against a disposable target site.
- **W3-2 — adapter task post-refactor:** Authentik broker-client hardening
  + audit enhancement (superseded form; revisit after W3-1 proves the
  generic path).
- **W3-3 — OPEN:** screen-follow (v1 feature not yet carried to v2).
- **W3-4 — OPEN:** agent input via native chat panel (v1 had neko chat; v2
  has none).
- **W3-6 — NOT STARTED:** CRMOC rollout + transversal/service browsers.
  Gated behind W3-1 boundaries being proven.
- **W3-5 — isolated PoC only** (agent-browser companion); W3-7 (tab
  snapshot) and W3-8 (ops/retention docs) source-verified but live adoption
  in v2 still pending.

### Open — v1 → v2 parity gaps (v2 is behind the v1 fleet today)

- **No video/streaming surface:** v1 had a neko-based interactive viewer; v2
  viewer is a bounded HTML/relay shell (no WebRTC/screen stream, no real
  screen-follow). Biggest user-visible gap.
- **Single slot deployed:** compose wires `slot-1` only (`CB_SLOT_SUPERVISOR_URLS`,
  `CB_AGENT_CONTROL_URLS`); v1 ran a multi-slot fleet with queueing. Router
  code supports a slot map but the deployment has one slot.
- **No agent chat panel** (W3-4), **no screen-follow** (W3-3).
- Idle suspend/resume exists in lifecycle code but is not the tuned v1
  behavior; W3-7 tab snapshot restore not wired into the live surface.
- Broker auto-relogin absent (ties to W3-1).

### W4 — replan (original MVP target ≤ 2026-09-13 is lapsed)

Per `roadmap-w3-status.md`: "W4: replan after the broker-boundary
refactor". Proposed W4 sequencing (needs Tigo approval):

1. **W3-1 E2E broker login proof** (highest value, core refactor promise).
2. **Streaming/surface decision for the viewer** — approve a mechanism
   (neko/WebRTC integration vs enhanced relay) before building; this decides
   W3-3/W3-4 feasibility on v2.
3. **Second slot + queue demo** (capacity + waiting-room parity).
4. Then CRMOC/service browsers (W3-6) and v1 decommission decision.

### Phase 6 (CloudFiles slice) — status

Phase 6 was scoped as "production rollout" of CloudFiles. With dev01 == prod
(Tigo, 2026-09-08) the stack already serves its final domains, so Phase 6
reduces to: any extra hardening Tigo wants for real user traffic. No
environment build-out remains.

## Phase 6 production landscape (read-only discovery, 2026-09-08)

Verified live (subagent: DNS digs, Coolify API GETs, docker/DB reads;
Artifacts: `/workspace/prod-discovery/coolify-api-services69-apps.txt`,
`coolify-db-services-all89.txt`):

- **Dev and prod are the SAME environment for now (Tigo, 2026-09-08):**
  there is no separate prod Coolify, no separate prod host, and no new DNS
  to create — the dev01 deployment IS production. `deploy.aikumi.app`
  (Coolify 4.3.18 on mother01) is the only instance; the
  `COOLIFY_TOKEN_PROD` env/VW field names the token for this instance
  (field `COOLIFY_TOKEN_PROD` in VW item `dd2d937f-…6499` = "hermes_env_dev";
  401 without token; token may contain `|` — never pass it through ssh argv,
  use stdin/file).
- **Domains are already set up**: `cloudbrowser2.dev01.pmo.city` and
  `cloudfiles2.dev01.pmo.city` resolve (CNAME `mother01.on-ai.sbs` →
  145.223.34.130) and are managed by Coolify/Traefik on service
  `nievufka…`. Apex-`pmo.city` subdomains (e.g. `cloudbrowser.pmo.city`)
  have no records — that is fine and NOT a gap; do not propose DNS or
  Cloudflare changes (forbidden: Tigo forbids touching Cloudflare).
- **No prod CloudBrowser exists yet**: the three running CloudBrowser
  services (v2 `nievufka…`, v1 `4guplgcr…`, older fleet `okixw2f…`) all
  serve only `*.dev01.pmo.city` on mother01. Mother02 (37.27.218.196) runs
  no CloudBrowser; mother03 is API-hidden/likely unvalidated.
- **Apex-`pmo.city` records** (verified, informational only):
  `cloudbrowser2.pmo.city`, `cloudfiles2.pmo.city`, `auth.pmo.city` have no
  DNS records; `secrets.pmo.city` → CNAME `mother01.on-ai.sbs` →
  145.223.34.130. These apex subdomains are not used by CloudBrowser and
  are NOT a Phase 6 dependency.
- **IdP is already prod-ready**: Authentik on mother01 (auth.aikumi.app,
  2025.8.1) serves application `pmoc-sso` (OAuth2 provider #37) with live
  OIDC discovery at
  `https://auth.aikumi.app/application/o/pmoc-sso/.well-known/openid-configuration`;
  the compose already pins `CB_OIDC_ISSUER` to it. `auth.pmo.city` has no
  DNS and is only the declared launch/callback target.
- Coolify manages 3 servers (mother01 host.docker.internal, mother02
  37.27.218.196, mother03 hidden); team "On-AI Side-by-Side"; 69
  API-visible services (89 incl. mother03 in DB).

Phase 6 preflight still required before any approval: TinyAuth/Authentik
groups policy for the prod-facing apps, and a decision on whether Phase 6
needs a separate second deployment at all given dev01 == prod for now
(dev01 already serves the v2 stack on its final domains).

## Standing constraints

- Never commit/push outside task-authorized scope.
- Identity: `Remote-Sub`/`Remote-User` only via identity-link resolution;
  `Remote-Email` never authoritative; PMO ids minted server-side.
- `CB_EDGE_AUTH=traefik-forwardauth` fail-closed; no session without a
  resolvable principal.
- No compose-level Traefik routers; no host-published ports for internal
  services; routing only via existing Coolify-managed domains.
- Old layout is called "prior", never "legacy" (test gate).
- Gates before every commit: `uv run make check`, boundary suite,
  `compileall`, `git diff --check`. `.hermes/` never staged.