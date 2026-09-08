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

Awaiting Tigo's UI retest at the public host; then this milestone is closed.

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
- Image digest sync to `949faea` build (run `34231460028`); viewer live on
  dev01 at digest `2968da87…` — `e4740e9`

## Next milestones (dependency order)

1. ~~Viewer frontend + interactive surface~~ — **implemented, deployed, in
   user retest.** Pending only Tigo's confirmation at the public host.
2. **Spec alignment (was plan §3.6)** — add `POST /v1/agent/<op>` and
   `POST /v1/session/activate` to `specs/contracts/control-api/v1/openapi.yaml`;
   refresh stale phase statuses in `specs/proposals/v0.2/91-…` (still say
   "Phase 0 pending"). Local, no live changes.
3. **Session-TTL product decision (backlog)** — TTL runs from creation, not
   last activity; a 1-hour active session is cut off the same as an idle one.
   Candidate: sliding renewal on authenticated activity. Decision needed from
   Tigo before wiring.
4. **Live hygiene (dev01 only, separate approval each)** — cosmetic
   first-activate `supervisor_unavailable` race (wake succeeds; bounded retry
   is the current workaround; candidate for a spec note); stale static binding
   values (`principal-dev01` etc.) in the Coolify env store are inert but
   would re-apply on a full re-render; `broker-state` volume orphaned in
   `deploy/coolify/compose.yaml`.
5. **Phase 6 production rollout** — separately approved; DNS, Traefik, prod
   Coolify mutation, real fleet.

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