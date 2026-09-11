# CloudBrowser development roadmap

Status: **M2a bounded task accepted; full M2 remains open. Tigo approved
viewer-before-application-login sequencing on 2026-09-11.** Development approval
does not establish security sign-off or deployment approval. M1 source implementation
and automated qualification are complete; see
[evidence](../../../docs/evidence/2026-09-11-m1-continuity.md). Independent
security approval remains separate; M1 evidence alone does not imply a live
multi-user acceptance.
M2 runtime source `2e300ef` passed **1078 tests with 7 explained skips** and all
six validators. Its nine images passed CI run `34623825124`, are pinned by
`b6fc6e1`, and run healthy on dev01. The isolated authenticated Hermes profile
passed start, tab listing, public-page open and exact-tab inspection. See
[evidence](../../../docs/evidence/2026-09-11-m2-browser-task.md). Live
application credentials, Vault grants and MFA are not part of this acceptance.
The roadmap originated from baseline `430a06603e8dff9531cc14042a01e38fff2b8874`.
This is the proposed forward plan. [PRODUCT-PRD.md](PRODUCT-PRD.md) defines
outcomes; [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md) records evidence.
Previous W3/W4 and CloudFiles phase numbers remain traceability references.

## Milestones and exit criteria

| Order | Milestone | Deliverable and exit evidence | Requirements |
| --- | --- | --- | --- |
| M0 | Establish a trustworthy baseline | Reproduce full tests including Compose; review the large broker change with explicit findings/disposition; verify current runtime/image provenance separately. Resolve or document release blockers. No GO claim from test counts alone. | CB-05, CB-10 |
| M1 | Prove personal ownership and consent continuity | Decide profile storage/slot switching and grant lifetime. Prove A → B → A slot reuse, restart/tab recreation, fresh capability issuance, revocation, and no cross-owner state. Deliver safe migration if the model changes. | CB-01, CB-02, CB-06, CB-09 |
| M2a | Authenticated Hermes browser control | First-tab creation, exact-target navigation/click/ordinary typing/page state and the supported Hermes entrypoint. Public-page acceptance recorded; review/merge gate open. No application-login claim. | CB-03 |
| M3a | Minimum live viewer and takeover | Disposable same-Chromium transport spike, authenticated owner-bound live view, target selection, exclusive keyboard/mouse takeover, explicit resume and reconnect. Human control pauses agent observation, input and broker login. | CB-04, CB-05 |
| M2b | Application login acceptance | After M3a, observe one approved non-production Basic/Authentik login, prove the intended account, and qualify consent, revocation, wrong-account/origin rejection and uncertain outcomes. Manual login alone does not qualify broker-driven login. | CB-05, CB-06 |
| M3b | Employee self-service access | User-facing consent/grant/revoke and recovery; observation cannot bypass agent secret restrictions. Operator provisioning is not self-service acceptance. | CB-04, CB-05, CB-06 |
| M4 | Qualify the integrated pilot | Demonstrate two employees and two slots, browser restart/recreate, CloudFiles download to local computer, recovery, backup/restore, and measured capacity. Build all nine images from a reviewed source SHA; verify provenance/SBOM; synchronize all pins and qualify clean install/rollback. | CB-01–CB-06, CB-08–CB-10 |
| M5 | Controlled rollout and acceptance | With deployment authorization, inspect existing state, back up, migrate/provision, roll out qualified images, and execute the signed-off user journeys. Record exact source/image IDs, failures, rollback criteria, and user acceptance. | Pilot requirements |
| M6 | Complete v0.2 login coverage | Add broker-only exact-target form capability, then stored TOTP and direct human code submission; qualify each supported site and full recovery path. Form remains disabled until its gate passes. | CB-07, CB-09 |
| M7 | Expand the product | Add screen-follow refinements/native agent chat, CRMOC/service principals, additional capacity/sites, and an independently approved prior-fleet migration/retirement. | Expanded scope |

Approved next sequence: review/fixes → close M2a → M3a → M2b → M3b → M4 → M5.
Documentation and transport feasibility may progress while review is blocked;
live credential enablement, merge and deployment must not bypass it. M2a is a
split of old M2, not a claim its login criteria were met. See
[viewer foundation](../../../docs/M3-VIEWER-FOUNDATION.md). M6 can move ahead of M5
if the selected pilot sites require MFA or ordinary forms. This is a site-driven
scope adjustment, not permission to bypass those requirements.

## Development decisions and sequencing

M1 uses stable owner storage and explicit durable consent under
[ADR-0005](../../adr/0005-m1-personal-state-and-consent.md). The M0 Linux baseline
is reproduced; its independent broker security review remains a release gate.
M1/M2 authorization does not waive that review. Employee self-service consent
is M3; current consent provisioning stays operator-controlled and offline.

1. Reproduce and record the source gates; resolve machine-dependent test
   requirements without weakening assertions or hiding skips.
2. Review capability replay/correlation, revocation races, crash/idempotency
   outcomes, exact targets, deadlines/SQLite waits, and secret directionality.
   Record findings against the immutable commit. Obtain a fresh review before
   calling the broker release-ready; the previous review was stopped.
3. Trace the profile directory through owner change and establish a real-browser
   A → B → A test. Inspect consent lookup across generation/tab changes and
   propose a migration-safe grant model. These are concrete product gaps to
   resolve before investing in release publication.
4. Write decisions for persistent profile selection, consent versus per-request
   authorization, and viewer transport. Keep decisions bounded to the existing
   product boundaries; prefer focused fixes over a general rewrite.
5. Deliver one reviewed change per acceptance outcome, with tests and updated
   status. Do not bundle another broad, unreviewed integration into `main`.

## Release and deployment policy

The current manifest declares installable and is image-qualified; clean-install
parity still needs qualification/correction. All nine image pins,
qualification records and provenance tests are synchronized to runtime source
`2e300ef`, CI run `34623825124` and release commit `b6fc6e1`. The dev01
deployment and bounded authenticated Hermes acceptance are recorded separately
from image qualification.

A user/operator or an authorized agent may trigger the build workflow. Token
budgets from previous tasks are not an enduring operational restriction.
Source changes, image qualification, deployment, and user acceptance have
different evidence and are recorded separately. Deployment authorization must
identify the environment, migration, qualification accounts/sites, and rollback.
Historical notes say dev01 also serves real users; confirm that before rollout
and do not assume it is disposable or requires new DNS.

## Definition of completion for each increment

- Requirement and user-visible acceptance are identified before implementation.
- Behavior changes have meaningful contract/security regression tests.
- `make check`, the CloudFiles boundary suite where relevant, and diff checks
  pass; every skipped gate is explained with its remaining qualification owner.
- Status links source SHA, test evidence, image qualification, and deployed
  acceptance independently. Historical results retain their dates and SHA.
- Documentation describes current behavior; proposed requirements remain
  marked proposed until approved. Approval does not imply a passing runtime.
- Release-changing increments include a migration and rollback plan.

## Planning assumptions and risks

No calendar deadline is promised from the inherited W3/W4 labels. Estimate the
next increment after M0/M1 expose the profile and consent work. The critical
risks are ownership across slot reuse, consent usability across ephemeral
bindings, real-site account proof, and viewer/input isolation. Form/MFA gaps
are known scope, not surprise release exceptions. Qualification must select
specific sites and evidence; a generic adapter name cannot establish support.

## Old-to-new roadmap mapping

| Previous item | New home |
| --- | --- |
| W3-1 and W3-2 broker/recovery | M0, M1, M2, M6 |
| W3-1A queue/identity | M1 and M4 regression acceptance |
| W3-3 screen-follow; W3-4 chat | M3 foundational view/takeover; M7 refinements/chat |
| W3-5 agent-browser PoC | M2 integration evaluation only if needed |
| W3-6 CRMOC/service browsers | M7 |
| W3-7 tab recovery | M1 and M4 |
| W3-8 operations; W4 installation | M4 and M5 |
| CloudFiles phases 0–5 | Existing source, preserved and requalified in M4 |
| CloudFiles phase 6 / Step 19 | M5 deployment and acceptance |
