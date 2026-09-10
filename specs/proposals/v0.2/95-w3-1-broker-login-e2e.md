# W3-1 — Broker Login E2E Proof

> Version: 0.1 — 2026-09-10
> Status: **PRE-LOGIN CHECKPOINT — not qualified**
> Milestone: establishes the source-level boundary and local acceptance plan;
> it does not claim final form/TOTP/human-handoff support or live Authentik
> closed-shadow qualification. It does not authorize production rollout, DNS
> changes, Coolify mutation, or credential rotation.

## Current status boundary

The final Credential Broker product requirements remain in
[`85-credential-broker-prd.md`](85-credential-broker-prd.md). This milestone
must not be read as shipping those requirements:

- **Form login:** the prior Layer 4 form proof is historical evidence only.
  Production `form` mode intentionally exits at startup, and the three Layer 4
  form integration tests are skipped until a broker-only exact-target form
  capability exists.
- **Authentik SSO:** the current capability detects the Authentik MFA stage and
  returns `mfa_required`/`unsupported` as appropriate. It does **not** submit
  TOTP, and it does **not** provide a human one-time-code handoff.
- **Live qualification:** closed-shadow Authentik qualification, live image
  qualification, deployment, and real browser/Vaultwarden proof are not
  qualified. They are outside the current pre-login checkpoint.

## Goal

Prove the secure boundary end-to-end in stages: Hermes requests a login
intent → broker resolves the principal's binding → broker fetches a
Vaultwarden grant through the broker-only path → a qualified adapter performs
its bounded action in the slot browser → broker returns a status-only
`BrokerResult` to the agent with a redacted audit event. The agent never sees
plaintext credential material; the slot browser holds the session and the
broker is the only process that touches the grant.

## Scope

### 1. Vaultwarden producer

`fetch_credentials(username_ref)` injectable that resolves a Vaultwarden
item, decrypts it through the broker-only path, and returns material only to the
broker coordinator.

- HTTPS-only Vault client, scoped to one item per call.
- Item resolution is through a principal-scoped durable grant authorization;
  the caller cannot choose a global item reference.
- Material shape is adapter-specific and remains broker-internal.
- Attachment handling is out of scope; return a bounded unsupported status.
- Every fetch emits a redacted event; no material appears in event fields.

### 2. Adapter qualification states

| Adapter/path | Current checkpoint | Qualification needed before claim |
|---|---|---|
| `basic` | Local exact-origin capability and contract coverage | Published image, live runtime, and controlled live E2E |
| `form` | **Disabled at production startup**; prior local form proof is historical | Broker-only exact-target capability, then unskip the three Layer 4 tests and run live E2E |
| `sso` / Authentik | MFA stage detection only; no TOTP submission or human handoff | Controlled Authentik closed-shadow run, TOTP submission, human one-time-code handoff, and application identity proof |

A local test pass is not a live qualification result. A source commit is not an
image digest or deployment result.

### 3. Negative proofs (security invariants)

- Vault producer never accepts credentials from the agent.
- Adapter receives material only inside the broker process; never via env or
  response.
- `Remote-Email` is never used as a vault key.
- Legacy direct-store/decryption paths are unreachable from production HTTP.
- Audit events for attempted credential egress fail closed.
- Form mode exits rather than silently running an unqualified capability.
- MFA detection never becomes implicit TOTP submission or an unbounded retry.
- The runtime status and README must keep the principal-scoped durable grant,
  idempotency, nonce, and capability boundary visible when interfaces change.

## Out of scope for this checkpoint

- Form-login production support and the historical form Layer 4 proof being
  treated as shipped qualification.
- TOTP submission, human one-time-code handoff, or any unsupported MFA bypass.
- Live Authentik closed-shadow qualification, image publication, digest sync,
  deployment, or real browser/Vaultwarden login proof.
- W3-3 screen-follow, W3-4 chat panel, W3-6 CRMOC rollout, and v1 fleet
  decommission.

## Architecture decisions to confirm before live qualification

1. Vault session strategy and rotation handling.
2. Exact-target broker-only browser capability for ordinary forms.
3. Authentik closed-shadow test application and synthetic principal.
4. Human one-time-code routing, TTL, single-use semantics, and operator/user
   handoff boundary.
5. Release sequence: source commit → user-triggered Actions build →
   digest/provenance sync → separate deployment/qualification approval.

## Test plan

- Contract tests for the durable principal-scoped grant, idempotency, nonce,
  capability, binding, target-preflight, and status-only boundaries.
- Startup guard test proving `CB_BROKER_ADAPTER=form` exits closed.
- Three historical Layer 4 form integration tests remain skipped while form
  mode is disabled; they are not counted as shipped qualification.
- Authentik contract tests cover declared origins, MFA detection, unsupported
  stages, and application identity proof. They do not claim TOTP submission or
  human handoff until those capabilities are implemented and qualified.
- Installation/release tests verify the source contract and provenance record;
  they do not turn stale pins into current release evidence.

## Sequencing

1. Commit the source, status docs, and consistency tests.
2. Run local validators; record the source commit.
3. Have the user/operator trigger the approved GitHub Actions build because the
   current token limits prevent an automatic trigger.
4. After CI passes, synchronize immutable image digests and provenance records
   in a separate release change. Do not edit those pins in this checkpoint.
5. Run the provenance and full gates against the synchronized release.
6. Only after explicit approval, perform live deployment and Authentik
   closed-shadow qualification.
7. Update `roadmap-w3-status.md` and the durable plan only from the resulting
   evidence; do not mark W3-1 PASS from local source tests alone.

## Constraints

- Identity only via identity-link → `Remote-Sub`/`Remote-User`;
  `Remote-Email` never authoritative.
- No plaintext credential material in any response body, env, log, or audit
  field; only bounded status metadata.
- Grant, idempotency, and nonce state are durable and principal/request scoped.
- `git diff --check` clean; `.hermes/` never staged.
- Verification only via `uv run`; no system pytest; no ruff; no Docker compose
  plugin.
