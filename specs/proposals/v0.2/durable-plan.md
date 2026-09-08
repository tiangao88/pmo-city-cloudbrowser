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
5. **Phase 6 production rollout** — separately approved; DNS, Traefik, prod
   Coolify mutation, real fleet.

## Phase 6 production landscape (read-only discovery, 2026-09-08)

Verified live (subagent: DNS digs, Coolify API GETs, docker/DB reads;
Artifacts: `/workspace/prod-discovery/coolify-api-services69-apps.txt`,
`coolify-db-services-all89.txt`):

- **Prod and dev Coolify are the SAME instance** (`deploy.aikumi.app`,
  Coolify 4.3.18 on mother01) — there is no separate prod Coolify. "Prod
  rollout" therefore means: same instance, new service, prod domains.
  The `COOLIFY_TOKEN_PROD` env/VW field names the token for this instance
  (field `COOLIFY_TOKEN_PROD` in VW item `dd2d937f-…6499` = "hermes_env_dev";
  401 without token; token may contain `|` — never pass it through ssh argv,
  use stdin/file).
- **No prod CloudBrowser exists yet**: the three running CloudBrowser
  services (v2 `nievufka…`, v1 `4guplgcr…`, older fleet `okixw2f…`) all
  serve only `*.dev01.pmo.city` on mother01. Mother02 (37.27.218.196) runs
  no CloudBrowser; mother03 is API-hidden/likely unvalidated.
- **Prod DNS does not exist yet**: `cloudbrowser2.pmo.city`,
  `cloudfiles2.pmo.city`, `cloudbrowser.pmo.city` have no records
  (NXDOMAIN); `secrets.pmo.city` → mother01 is the existing pmo.city
  pattern to copy (CNAME `mother01.on-ai.sbs` → 145.223.34.130).
- **IdP is already prod-ready**: Authentik on mother01 (auth.aikumi.app,
  2025.8.1) serves application `pmoc-sso` (OAuth2 provider #37) with live
  OIDC discovery at
  `https://auth.aikumi.app/application/o/pmoc-sso/.well-known/openid-configuration`;
  the compose already pins `CB_OIDC_ISSUER` to it. `auth.pmo.city` has no
  DNS and is only the declared launch/callback target.
- Coolify manages 3 servers (mother01 host.docker.internal, mother02
  37.27.218.196, mother03 hidden); team "On-AI Side-by-Side"; 69
  API-visible services (89 incl. mother03 in DB).

Phase 6 preflight still required before any approval: prod DNS records,
TinyAuth/Authentik groups policy for the prod apps, and a decision on which
host/instance-id to use (a second CB_INSTANCE_ID on mother01 vs mother02).

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