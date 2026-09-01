# W3 Scope — CloudBrowser carry-over and expansion

> **Scope boundary — 2026-08-28/29.** W3 contains work intentionally removed
> from the W2 exit gate. W2 is complete: its own gate is green and accepted.
> W3 work was not used to close a yellow W2 row. These items are not unfinished
> W2 DoD.
>
> **Dates:** Aug 31–Sep 6 · **Phase:** CRMOC teams. The original calendar
> window remains historical; the current workstream is the specification and
> refactor reset recorded in `08-roadmap.md` on 2026-09-01.

## W3 entry rule

Start this scope after W2's own exit gate and Tigo's pilot sign-off are green;
that condition was met on 2026-08-29. If a future W2 correction is identified,
it remains a W2 blocker and must not be relabeled W3 just to make the status
green.

## Current status snapshot — 2026-09-01

- **W2:** complete and accepted. No W2 row is being reopened by this reset.
- **W3-1A:** **PASS** — live identity/queue reconciliation and visible identity
  separation passed.
- **W3-1 recovery:** **PASS** — owner-bound `/restart`, idle wake, and full
  service recreate recovery passed, including durable archive restore.
- **W3-1 strict authenticated surface:** **PARTIAL / NOT PROVEN** — the
  broker-driven auto-relogin and trusted authenticated-surface proof are not
  established through the intended generic broker path.
- **W3-5:** complete as an isolated local PoC only; no production adoption.
- **W3-7:** source/test verified only; no live deployment.
- **W3-8:** documentation/contract verified only; no live deployment.
- **Refactor reset:** specification work is now the immediate W3 activity.
  W3-6 rollout, service-browser adoption, and production adoption do not
  follow automatically from the completed packages.

## Why W3 is being reset before more implementation

The live Unlatch exercise exposed a product-boundary mismatch. The one-off
helper could unwrap and decrypt a user's grant directly inside a slot and fill
an existing tab. That proved the grant material can support an application
login, but it was **not broker proof** and it bypassed the intended broker-only
credential boundary. The deployed `sso-broker.py` is currently an
Authentik/TinyAuth-specific broker, while FR-9 describes a generic
Vaultwarden-backed credential broker for declared sites.

This is a specification and architecture gap, not a reason to mark W3-1 green.
The refactor documents are:

- `85-credential-broker-prd.md` — product requirements and acceptance contract;
- `86-product-boundaries.md` — ownership, trust, and non-goals;
- `87-broker-security-model.md` — capability boundary and security tests.

## W3 work packages

### W3-1 — Authenticated surface continuity after recovery

**Status: PARTIAL / NOT PROVEN (2026-09-01).** Owner-bound recovery is green;
the strict authenticated-surface gate remains open. The current accepted
criteria are:

- [x] `/restart`, idle wake, and full service recreate are owner-bound and
      archive-safe.
- [x] Spec-56 identity-cookie stripping remains in force; no identity cookie is
      copied between users or restored from an archive.
- [x] Wrong-owner, duplicate-cookie, stale-grant, and failed-reauth cases fail
      closed in the existing recovery/session controls.
- [ ] A generic broker operation authenticates a declared trusted application
      for the immutable owner without exposing credentials to the agent.
- [ ] A broker-driven re-login is recorded, including owner match and
      authenticated application success proof.
- [ ] The strict authenticated-surface qualification is repeated after
      `/restart`, idle wake, and full service recreate through the new broker
      boundary.

Evidence for the recovery pass: `/opt/data/w3-1-recreate-trigger-2026-08-31.json`,
`/opt/data/w3-1-recreate-monitor-2026-08-31.json`,
`/opt/data/w3-1-recreate-verification-2026-08-31.json`, and
`/opt/data/w3-1-recreate-fixed-2026-08-31.json` (sanitized local artifacts).

### W3-1A — Identity and queue-state reconciliation

**Status: PASS (2026-09-01).** The live two-browser matrix showed:

- `spike-user@aikumi.pro` seeing its own queued state at position 1;
- `montigaud@aikumi.pro` seeing its own active browser;
- identities remaining separated with no stale `?` or substitution.

The local readiness/queue contract and deployed live behavior are recorded in
`81-w3-1a-identity-queue-reconciliation.md`. This package is closed; it is not
the generic broker refactor.

### W3-2 — Dedicated broker IdP client and audit enhancement

**Status: BLOCKED / SUPERSEDED BY REFACTOR.** Revisit after the broker product
boundary is baselined. Authentik should become an adapter/use case, not the
product definition. The generic audit contract is covered by the refactor
specifications and W3-8.

### W3-3 — Screen-follow (explicitly removed from W2)

**Status: OPEN.** Remains separately gated. No work is authorized by this
specification reset.

### W3-4 — Agent in the native neko chat panel

**Status: OPEN.** Remains separately gated. No work is authorized by this
specification reset.

### W3-5 — Agent-browser companion and productization

**Status: COMPLETE — ISOLATED ONLY.** `84-w3-5-agent-browser-poc.md` records a
local PoC pass and recommends agent-browser as a companion instrument around
browser-use, not a replacement. No live-fleet adoption occurred. Production
adoption still requires owner-aware integration, artifact redaction/retention,
supply-chain pinning, and a repeated fixed-task corpus.

### W3-6 — Broader CRMOC rollout and transversal/service browsers

**Status: OPEN / NOT STARTED.** Do not roll out until personal versus service
ownership, the broker boundary, credential scopes, and agent authorization are
designed and verified.

### W3-7 — Tab-loss and lifecycle hardening

**Status: COMPLETE — SOURCE/TEST VERIFIED, NOT DEPLOYED.** `restart-api.py`
maintains `tab-snapshot.json` and an independently atomically-written
`tab-snapshot.last-good.json`. Valid live state, including an intentional empty
workspace, remains authoritative; fallback occurs only for malformed/unreadable
live state. Authentik flow pages remain filtered and owner-mismatch teardown
clears both copies. Focused coverage is
`scripts/test-w3-7-last-good-snapshot.py` (7/7); no live deployment occurred.

### W3-8 — Operational and audit expansion

**Status: COMPLETE — DOCS/CONTRACT VERIFIED, NOT DEPLOYED.**
`82-w3-8-operations-and-audit.md` and the W4 checklist were verified locally;
no live deployment or fleet mutation occurred.

## W3 refactor gate

Before further W3 implementation or rollout, baseline the following documents
and obtain agreement on their acceptance criteria:

1. Cloud Browser product boundary;
2. generic deterministic credential broker boundary;
3. Hermes-profile, principal, and browser-owner binding;
4. agent/CDP capability boundary;
5. form, HTTP Basic, SSO, and MFA adapters;
6. Vaultwarden grant/token custody and revocation;
7. login success verification and failure semantics;
8. audit, redaction, and retention;
9. migration, compatibility, and rollout criteria.

After that baseline, recut W3/W4 dates and turn each accepted requirement into
implementation and verification work. This register does not authorize a
deploy, restart, credential rotation, or fleet mutation.

## W3 non-goals

W3 does not silently absorb any W2 blocker. The W2 gate is green and complete;
the following remain historical boundary checks only:

- D1 pilot identity/isolation acceptance and sign-off — ✅ W2 complete;
- D9 final three-day soak verdict — ✅ W2 complete;
- D14 CRM pilot validation and Tigo's W2 sign-off — ✅ W2 complete.

D3/D15 is green and closed for W2. Its strict authenticated-surface continuity
is W3-1. D13 is W3-3. The W3-5 PoC does not authorize production adoption.

## Relationship to other records

`08-roadmap.md` is the current high-level status record. This file is the W3
package register. `23-d15-sso.md` records the Authentik/TinyAuth W2 path and
must now be read as an adapter-specific historical implementation, not as the
complete generic broker contract. `28-w3-agent-chat.md` remains the detailed
design for W3-4.
