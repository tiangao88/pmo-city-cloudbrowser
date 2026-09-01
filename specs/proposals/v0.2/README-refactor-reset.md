# Cloud Browser — PRD and Specification Reset

> Version: **0.1 — 2026-09-01**  
> Status: **PROPOSED FOR REVIEW**  
> This is the new entry point for the refactor discussion. It is not an
> implementation or deployment authorization.

## Why this reset exists

The original Cloud Browser design correctly established the desired principle:
Hermes requests a login intent, a deterministic broker uses Vaultwarden
material, and the agent never receives the password. The implementation and
specification later diverged:

- the deployed `sso-broker.py` is an Authentik/TinyAuth-specific watcher and
  filler, not a generic declared-site broker;
- ordinary website credentials such as the Unlatch item are not handled by the
  deployed broker;
- a one-off in-slot helper was able to load the vault client, decrypt a grant,
  and fill a live tab, proving an operational bypass of the intended broker-only
  boundary;
- the full-control agent/CDP surface does not yet prove that cookies, storage,
  network bodies, password values, or grant material are inaccessible;
- HTTP Basic Auth, arbitrary SSO, generic success verification, unsupported MFA,
  profile-scoped broker authorization, and migration behavior are not specified
  precisely enough.

The refactor must resolve the boundary before adding more W3 implementation.

## Document set

| Document | Role |
|---|---|
| `85-credential-broker-prd.md` | Product requirements, journeys, adapter contract, acceptance criteria |
| `86-product-boundaries.md` | Product map, actor ownership, trust boundaries, current-component classification |
| `87-broker-security-model.md` | Security invariants, threat model, capabilities, denylist, attack matrix, migration controls |
| `02-functional-requirements.md` | Existing baseline requirements; update after this proposal is agreed |
| `07-agent-api.md` | Existing draft control surface; update after capability policy is agreed |
| `23-d15-sso.md` | Historical/implemented Authentik-TinyAuth adapter path; not the generic broker definition |
| `34-granthub.md`, `59-grant-session-leg.md` | Existing consent, grant, and session-leg behavior to reconcile with the new custody model |
| `82-w3-8-operations-and-audit.md` | Existing operational audit and redaction baseline |

## Proposed product boundary

```text
Hermes agent
  └─ intent-only request, scoped to current profile/principal
       ↓
Cloud Browser router/control plane
  ├─ derives identity and browser owner
  ├─ validates site declaration and capability
  └─ sends opaque broker authorization
       ↓
Credential Broker
  ├─ consumes the per-principal grant
  ├─ executes a reviewed login adapter
  ├─ uses a restricted browser fill capability
  └─ returns status-only result
       ↓
Owner's Chromium browser
```

The Cloud Browser runtime owns lifecycle, routing, viewer, profile persistence,
queueing, and restricted page-state control. The Credential Broker owns
credential consumption, adapter execution, and login verification. Vaultwarden
remains the source of credential material. GrantHub remains the consent and
revocation surface. No component may quietly absorb another component's
credential authority.

## Current proposed decisions

These are the baseline proposals for discussion, not yet final product
decisions:

1. **Generic broker:** form login, HTTP Basic, SSO, TOTP, and one-time human
   code handoff are adapter classes behind one intent API.
2. **Authentik:** retain the current Authentik/TinyAuth flow as an explicit SSO
   adapter; do not define the whole broker around it.
3. **Owner binding:** profile, principal, browser, slot, target tab, site, and
   request nonce are server-derived or cryptographically bound; caller-supplied
   identity is never authoritative.
4. **Broker-only custody:** the agent/slot cannot read grants, decrypt vault
   items, or reach the legacy direct-decryption fallback. A separate broker
   service is preferred; a sidecar is acceptable only if equivalent isolation is
   demonstrated.
5. **Restricted CDP:** the normal agent surface cannot read cookies, storage,
   network bodies, password values, or unrestricted runtime state. The broker
   gets only a request-scoped fill/verification capability.
6. **Fail closed:** ambiguous forms, undeclared origins, wrong-owner state,
   revocation, unsupported MFA, challenge loops, and unverifiable success stop
   without guessing or silent fallback.
7. **Recovery:** spec-56 identity-cookie stripping remains mandatory. Recovery
   proof must use the same broker contract as ordinary login.
8. **Sensitive artifacts:** HARs, screenshots, recordings, traces, and crash
   output are sensitive by default and require redaction/retention controls.

## What remains open for the planning discussion

- separate broker service versus broker-only sidecar;
- capability-token issuer and exact Hermes-profile binding;
- site declaration format, ownership, review, and update workflow;
- first production adapter set and test sites;
- MFA handoff transport and TTL;
- exact CDP mediation/denylist enforcement point;
- GrantHub versus broker custody split;
- migration and rollback strategy;
- revised W3/W4 release dates.

## Planning order

The recommended refactor sequence is:

1. Agree this boundary and resolve the open product decisions.
2. Convert the baseline proposal into versioned PRD, architecture, data-flow,
   API, and security specifications.
3. Write failing contract/security tests for authority, isolation, adapters,
   redaction, revocation, and recovery.
4. Build the broker boundary before moving the existing Authentik adapter.
5. Implement the ordinary form adapter using Unlatch as the first real proof.
6. Add HTTP Basic and broader SSO/MFA adapters only after the boundary tests are
   green.
7. Migrate the Cloud Browser router/CDP surface and remove direct slot helper
   access.
8. Re-qualify W3-1 authenticated recovery and only then revisit W3-2/W3-6 and
   the W4 launch date.

## Current status

W2 is complete and accepted. W3-1A, owner-bound recovery, W3-5 isolated PoC,
W3-7 source/test work, and W3-8 documentation work are recorded separately in
`08-roadmap.md` and `28-w3-scope.md`. W3-1 strict authenticated-surface
continuity remains partial/not proven. This reset does not authorize a deploy,
restart, credential operation, or production rollout.
