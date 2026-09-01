# CloudBrowser v0.2 baseline

- Baseline ID: `v0.2.0`
- Status: **approved for test-first implementation; not installable**
- Approved: 2026-09-01
- Source proposals: `specs/proposals/v0.2/`

## Scope

This baseline adopts the v0.2 proposal as the authority for the next
implementation phase:

- CloudBrowser runtime and Credential Broker remain separate products.
- Broker requests are profile/principal/site bound and return status only.
- Credential material is broker-only and exists only in broker memory during an
authorized operation.
- Agent control is restricted: no credentials, cookies, storage values, network
bodies, authorization headers, raw CDP, unrestricted evaluation, filesystem, or
process control.
- Site declarations are exact-origin, versioned, and immutable for each request.
- Unsupported, ambiguous, failed, revoked, stale, or cross-owner operations fail
closed.
- MFA may use a broker-held TOTP seed or an explicit human handoff; unsupported
MFA is not guessed.
- Success requires application-level identity verification, not infrastructure
health alone.
- Legacy Authentik/TinyAuth behavior is migration-only and cannot become a
cross-user or generic fallback.

## Required implementation gates

Implementation proceeds in this order:

1. Write failing contract, capability, binding, redaction, and replay tests.
2. Implement the smallest Credential Broker vertical slice behind those tests.
3. Extract owner-bound browser lifecycle behavior from `legacy/` only through
   tests and explicit migration adapters.
4. Add service health, images, backup/rollback, and `CB_INSTANCE_ID` isolation.
5. Produce an installable release only after the acceptance matrix is green.

This baseline authorizes code and test work only. It does not authorize
credential rotation, live-fleet mutation, Coolify deployment, or production
release.

## Traceability

- Requirements: `specs/proposals/v0.2/85-credential-broker-prd.md`
- Boundaries: `specs/proposals/v0.2/86-product-boundaries.md`
- Security invariants: `specs/proposals/v0.2/87-broker-security-model.md`
- Contract surfaces: `specs/contracts/`
- Architectural decisions: `specs/adr/`
