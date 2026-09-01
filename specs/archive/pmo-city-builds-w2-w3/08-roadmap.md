> **Scope correction — 2026-08-28/29:** W2 was a binary all-green pilot gate.
> Every retained W2 exit row is now green, evidence-linked, and accepted by
> Tigo. Deliberate W3 carry-over is not an open W2 item. See
> `28-w3-scope.md` and `78-w2-scope-correction.md`.
>
> D13 screen-follow is explicitly W3-3, not a W2 exit row. Strict D15 authenticated-surface continuity is explicitly W3-1. D1, D9, and D14 are now green with evidence and acceptance recorded. **D3/D15 is green and closed for W2. W2 is COMPLETE.**

# Roadmap — Cloud-Browser Service

> Status: **W3 ACTIVE — roadmap recorded 2026-09-01.** W2 is complete. W3-1A
> queue/identity reconciliation is **PASS**; owner-bound recovery is **PASS**;
> the strict W3-1 authenticated-surface gate remains **PARTIAL / NOT PROVEN**
> because broker auto-relogin through the intended broker path is not proven.
> The current blocker is a product-boundary/specification gap: the deployed
> `sso-broker.py` is Authentik/TinyAuth-specific, while FR-9 describes a generic
> Vaultwarden-backed credential broker. W3-7 and W3-8 are complete; W3-5 is
> complete as an isolated PoC only. Refactor planning is now the next activity;
> no W3-6 rollout or production adoption follows automatically.

## Timeline (4 weeks — original MVP target ≤ 2026-09-13)

| Week | Dates | Phase | Focus |
|---|---|---|---|
| **W1** | Aug 17–23 | **CLOSED** | POC on dev01 — single Chromium, CDP control, persistence, viewer, downloads, capacity measurements |
| **W2** | Aug 24–30 | **COMPLETE** | Pilot — Tigo + testers; retained W2 gate rows green, evidence-linked, and accepted |
| **W3** | Aug 31–Sep 6 | **ACTIVE — refactor/specification reset** | Record W3 status; complete the generic credential-broker PRD and product boundaries; then agree the refactor plan. Existing W3 packages remain separately gated. |
| **W4** | Sep 7–13 | **REPLANNING REQUIRED** | Original Groupe Alsei MVP-live target is not an automatic commitment; revisit after the broker refactor scope, security boundary, and acceptance plan are agreed |

## W3 package register (status at 2026-09-01)

| Package | Status | Record |
|---|---|---|
| **W3-1** | **PARTIAL / NOT PROVEN** | Owner-bound `/restart`, idle wake, and full recreate recovery pass. Strict authenticated-surface continuity remains open: broker auto-relogin and trusted authenticated-surface proof are not established through the intended generic broker path. |
| **W3-1A** | **PASS** | Live two-browser identity/queue matrix passed: `spike-user@aikumi.pro` showed its own queued state at position 1; `montigaud@aikumi.pro` showed its own active browser; identities remained separated. |
| **W3-2** | **BLOCKED / SUPERSEDED BY REFACTOR** | Dedicated Authentik broker-client and audit enhancement cannot be treated as the next step while the broker product boundary is unresolved. Revisit as an adapter-specific task after the refactor design. |
| **W3-3** | **OPEN** | Screen-follow remains separately gated. |
| **W3-4** | **OPEN** | Agent in native neko chat panel remains separately gated. |
| **W3-5** | **COMPLETE — ISOLATED ONLY** | `84-w3-5-agent-browser-poc.md`: local PoC passed; adopt as a companion instrument around browser-use, not as a replacement; no live-fleet adoption. |
| **W3-6** | **OPEN / NOT STARTED** | Broader CRMOC rollout and transversal/service browsers remain unstarted. Do not roll out until ownership, credential, and broker boundaries are designed and verified. |
| **W3-7** | **COMPLETE — SOURCE/TEST VERIFIED, NOT DEPLOYED** | Durable last-good tab snapshot extension and regression coverage passed; no live deployment. |
| **W3-8** | **COMPLETE — DOCS/CONTRACT VERIFIED, NOT DEPLOYED** | Operations, audit, retention, and W4 checklist completed locally; no live deployment or fleet mutation. |

## Current W3 gate and evidence

### Passed

- W2 exit gate: complete and accepted.
- W3 entry condition: W2 and pilot sign-off met on 2026-08-29.
- W3-1 owner-bound recovery: durable `sessions:/data/sessions` mount restored;
  full service recreate re-bound the recovered browser to its owner and
  restored the archived workspace tabs.
- W3-1A implementation and live matrix: readiness/queue reconciliation and
  visible identity separation passed.
- W3 isolation tests T6–T10: live green.
- W3-5 isolated agent-browser PoC: pass with companion recommendation.
- W3-7 and W3-8: local implementation/documentation verification passed.

### Open or superseded

- W3-1 strict authenticated-surface gate: not proven. The existing Unlatch
  authenticated-surface exercise used a one-off direct vault-decryption helper;
  it is evidence that the grant material can work, **not broker proof**, and
  it exposed a broker-only boundary bypass that must be removed in the refactor.
- W3-2: hold until the generic broker boundary is decided; Authentik becomes an
  adapter/use case rather than the product definition.
- W3-3, W3-4, and W3-6: open and unchanged.
- W3-7: source/test verified only; no deployment.
- W3-8: docs/contract verified only; no deployment.
- W4 launch target: requires replanning; the original date is retained as
  history, not a current release promise.

## Refactor gate

Before further W3 implementation or rollout, agree and baseline the new
product specification for:

1. the Cloud Browser product boundary;
2. the generic deterministic credential broker boundary;
3. the Hermes-profile and user binding model;
4. the agent/CDP capability boundary;
5. login adapters and success verification;
6. Vaultwarden grant/token custody and revocation;
7. MFA and human handoff behavior;
8. audit, redaction, and retention requirements;
9. migration, compatibility, and rollout criteria.

After that baseline, re-cut W3/W4 dates and convert each accepted requirement
into implementation and verification work.

## Historical W3/W4 notes

The original W3/W4 timeline and package history remain in git history and the
individual package specifications. This register is the current status record;
it deliberately does not mark open work green and does not authorize deploys,
restarts, or fleet mutation.

## W1 autonomy & dependencies (2026-08-16 — Tigo review)

**Granted by Tigo (standing for cloud browser resources in PMO City dev):**
- **Deploys:** first + subsequent deploys of the cloud browser service —
  authorized, no per-deploy approval needed (dev env only).
- **Vaultwarden test item:** broker-spike test item may be created by the
  agent in Vaultwarden (one-time grant for W1 spike).
- **SSO/group-gate final verify:** Tigo logs in himself (no test account
  needed); agent verifies labels/middleware mechanically.
- **DNS:** `cloudbrowser.dev01.pmo.city` — wildcard `*.dev01.pmo.city`
  resolves to mother01 (verified) → no DNS action.

**Remaining human touchpoints (small):**
- Tigo logs in once for the group-gate + end-to-end check (Aug 23 outcome).
- Viewer choice + RAM numbers + broker verdict handed to Tigo as one-page
  summary (by design, decision input not blocker).

## Definition of done — W1 (POC on dev01, by Aug 23)

**Goal: prove the full chain for ONE user on ONE browser + produce the
numbers W2–W4 depend on.**

[Historical W1 DoD retained in prior sections and package documents.]

## Definition of done — MVP (W4, historical baseline)

- [ ] One browser per employee, persistent profile, many tabs (FR-2)
- [ ] Link-first access via Tinyauth SSO (FR-1/FR-3)
- [ ] Full-control MCP surface (FR-4, D1) + browser.list/attach (FR-11)
- [ ] Vaultwarden autonomous login via broker with hybrid 2FA (FR-6/FR-9/FR-10)
- [ ] Viewer live (FR-15, component chosen in W1)
- [ ] Downloads: always durable, flat area, viewer + chat access (FR-12)
- [ ] Capacity slots + reserved service slots (FR-16)
- [ ] Transversal agent browser (FR-14) — at least one service (CRM)
- [ ] EU-resident data (D4), no credentials in logs (FR-7)

## Gating risks (historical)

1. **Viewer spike:** component selection was completed in W1; the current live
   viewer remains operationally separate from the credential-broker refactor.
2. **Sovereign install:** Alsei server provisioning still starts before any W4
   release decision.
3. **Broker:** the original W4 broker target is now a refactor dependency, not
   a green implementation claim.

## After MVP (backlog, not committed)

- Firefox engine (C1 says Chromium only year 1)
- Read-only MCP mode (D1 deferred)
- Mic/camera in viewer (FR-15 best-effort)
- Queue position refinement

---

## Decision note — agent control: browser-use sole driver through W2; browser-use + agent-browser pair for W3 (2026-08-20, Tigo)

**Historical decision:** browser-use was the only driver through W2. The
isolated W3-5 PoC now recommends agent-browser as a companion deterministic
instrument, not a replacement. Adoption remains gated by the refactor and an
owner-aware adapter test.

## Current corrected W2/W3 boundary

- **W2:** **COMPLETE 2026-08-29**; all retained W2 rows are green, evidence-linked, and accepted. D3/D15 is green and closed for W2.
- **W3-1:** strict authenticated-surface continuity, generic broker proof, and owner-safe recovery behavior.
- **W3-1A:** live identity/queue reconciliation **PASS**.
- **W3-3:** screen-follow, explicitly removed from the W2 exit gate.
- Full W3 register: `28-w3-scope.md`; current refactor documents: `85-credential-broker-prd.md`, `86-product-boundaries.md`, and `87-broker-security-model.md`.
