# W3-1 — Broker Login E2E Proof

> Version: 0.1 — 2026-09-08
> Status: **STARTING (Tigo approved)**
> Milestone: closes the W3-1 "PARTIAL / NOT PROVEN" gate
> (`roadmap-w3-status.md`). Does not authorize production rollout, DNS
> changes, Coolify mutation, or credential rotation.

## Goal

Prove the refactor's core promise end-to-end: Hermes requests a login
intent → broker resolves the principal's binding → broker fetches a
Vaultwarden grant through the broker-only path → a typed adapter
performs the login in the slot browser → broker returns a status-only
`BrokerResult` to the agent with a redacted audit event. The agent
never sees plaintext credential material; the slot browser holds the
session and the broker is the only process that touches the grant.

## Scope

### 1. Vaultwarden producer (new)

`fetch_credentials(username_ref)` injectable that resolves a Vaultwarden
item from `https://secrets.pmo.city` (CNAME → `mother01.on-ai.sbs`,
145.223.34.130), decrypts it through the broker-only path, returns
material to the broker coordinator.

- Vault client: HTTPS only, master-password unlock via VW env in
  broker container, org key fallback, scoped to one item per call.
- Item resolution by `username_ref` (e.g. `"unlatch/prod"` or a full
  Vaultwarden item UUID).
- Material shape adapts per adapter: password/TOTP secret for `basic`
  and `form`; OAuth2 client config for `sso/Authentik`.
- Attachment handling: not in W3-1 scope; if encountered, return
  `unsupported_material` status.
- Encryption key empty (spec 87: "Authentik app policy enforces groups;
  enc key MUST be empty"). VW organization key is the master.
- Audit hook: every fetch emits a redacted event
  (`vault.fetched`, `vault.miss`, `vault.decrypt_failed`) — no
  material in the event fields, only item id + last-4 of any
  sensitive reference (mirrors COOLIFY_TOKEN_PROD pattern).

### 2. Adapter E2E proofs

For each adapter: Hermes intent → broker → vault fetch → adapter → tab
login → status-only result. Each adapter E2E has its own RED test file
that proves the chain works on dev01's real broker service.

| Adapter | Test site | Verification |
|---|---|---|
| `basic` | Disposable HTTP Basic Auth test page served from a temporary container in the broker's compose network | Tab shows authenticated state; broker returns `status=ok`; agent receives no password |
| `form` | Disposable username/password form served the same way | Tab shows authenticated state; broker returns `status=ok`; TOTP prompt is gated by the `totp` adapter, not folded into `form` |
| `sso` | Real Authentik `pmoc-sso` test app on `https://auth.aikumi.app/application/o/pmoc-sso/` | OAuth2 callback lands in the tab; broker returns `status=ok`; no client secret leaves the broker container |

Acceptance: three RED test files go GREEN against the running broker
service on dev01.

### 3. Negative proofs (security invariants)

- Vault producer never accepts credentials from the agent (only
  `username_ref`).
- Adapter receives material only inside the broker process; never via
  env, never via response.
- `Remote-Email` never used as vault key.
- Old `sso-broker.py` watcher path is unreachable (already removed;
  verify no leftover import).
- Audit event for an attempted credential egress fails closed.

## Out of scope (gated)

- W3-3 screen-follow, W3-4 chat panel, W3-6 CRMOC rollout.
- v1 fleet decommission.
- Apex `pmo.city` DNS / Cloudflare changes (forbidden by Tigo).
- Phase 6 (CloudFiles slice) hardening beyond what's already live.

## Architecture decisions to confirm before code

1. **Vault session strategy**: per-call BW unlock (slow, safe) vs
   long-lived BW session cached in broker container memory (fast,
   needs lock on container restart to force re-unlock). Recommendation:
   per-call unlock; if too slow we'll move to cached.
2. **Test site hosting**: spin a `python -m http.server` with Basic
   Auth + a tiny HTML form in a one-off container in the broker's
   compose network, not exposed externally.
3. **Authentik test app**: use the existing `pmoc-sso` (live
   discovery 2026-09-08 confirmed it has OAuth2 provider #37 with
   client_id `D6KUzb…KSe0`); broker uses a confidential client with
   client_secret stored as a VW item, not in compose.
4. **Tab lifecycle**: which slot does the test login target? dev01 has
   `slot-1`. Plan: tests use a dedicated test slot (`slot-test`) that
   the broker spins ephemerally per test, or reuses `slot-1` with
   explicit binding rotation to a test principal.

## Test plan (RED-first)

- `tests/contract/test_credential_broker_vault_producer.py` —
  resolves, decrypts, audits; denies unknown `username_ref`;
  redacts audit fields.
- `tests/contract/test_credential_broker_basic_e2e.py` — full chain
  against the disposable Basic Auth site.
- `tests/contract/test_credential_broker_form_e2e.py` — full chain
  against the disposable form site.
- `tests/contract/test_credential_broker_sso_e2e.py` — full chain
  against `auth.aikumi.app/application/o/pmoc-sso/` test app.
- `tests/security/test_credential_broker_material_egress.py` — proves
  the agent never sees plaintext; logs that the audit event has no
  material.
- Extend `tests/installation/test_credential_broker_installation.py`
  for the vault producer's env wiring (`BW_HOST`, `BW_PASSWORD`
  envs).

## Sequencing

1. Confirm the four architecture decisions above (single approval, not
   per-decision).
2. RED test files first; gate (`make check`) shows failures on the
   missing implementation.
3. Implement Vaultwarden producer.
4. Add disposable test sites; implement basic → form → sso E2E tests.
5. Run full gate; commit each adapter slice separately.
6. Push, trigger CI build, sync digests, redeploy dev01, run all three
   E2E tests against the live broker service.
7. Update `specs/proposals/v0.2/roadmap-w3-status.md`: W3-1 → PASS
   with evidence links.
8. Update durable plan: W3-1 closed; W4 reprioritization unblocked.

## Constraints

- Identity only via identity-link → `Remote-Sub`/`Remote-User`;
  `Remote-Email` never authoritative.
- No plaintext credential material in any response body, env, log, or
  audit field; only `last-4` references for human review.
- BW session never persisted to disk inside the broker container.
- `git diff --check` clean; `.hermes/` never staged; commit identity
  fixed.
- Verification only via `uv run`; no system pytest; no ruff; no docker
  compose plugin.
- All gates green before every commit: `make check`,
  `make cloudfiles-boundary`, `compileall`, `git diff --check`.
