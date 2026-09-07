# CloudBrowser v2 — Durable Plan (status as of 2026-09-07)

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
rotation) is implemented and verified live on dev-staging. The viewer backend
(authenticated session surface driving the router) is pushed and deployed.
The live fleet is healthy on the `d1ca5cf` build (digest sync `50c0dca`).

Current user-visible gap: the viewer page at `cloudbrowser2.dev01.pmo.city`
serves a 300-byte static placeholder — it never calls the session routes and
shows "No interactive browser surface is attached to this instance."
regardless of session state. This is expected behavior of the current build,
not a defect: the viewer frontend milestone has not been implemented yet.

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
- Image digest syncs — `8f7bf19`, `6f63594`, `df2dedc`, `149519a`, `50c0dca`

## Next milestones (dependency order)

1. **Viewer frontend + interactive surface** — the only user-facing gap.
   Shell auto-joins on load (`POST /ui/session/join`), polls
   `GET /ui/session`, activates on offer (`POST /ui/session/activate`), and
   attaches the interactive browser surface when a slot is bound. Fail-closed
   identity preserved; no principal values in the DOM. TDD; then digest sync
   and dev01 redeploy for Tigo retest.
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
