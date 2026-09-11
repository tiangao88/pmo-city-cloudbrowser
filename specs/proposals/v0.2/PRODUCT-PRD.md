# CloudBrowser product requirements

Status: **product consolidation; M2a → minimum viewer/takeover → M2b login
sequencing approved by Tigo on 2026-09-11**. This does not approve every
unresolved design choice or establish delivered functionality.
Source checkpoint: `430a06603e8dff9531cc14042a01e38fff2b8874`.
This proposal preserves the approved security baseline and the frozen CloudFiles
requirements. It does not declare unfinished functionality delivered. Proposed
release sequencing is in [ROADMAP.md](ROADMAP.md); implementation evidence is in
[IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md).

## 1. Product outcome

An employee has a personal Chromium workspace on the client's infrastructure,
accessible through company sign-in from any device. The employee and their
Hermes agent use the same browser. The employee can observe, take control, and
resume later. Hermes can carry out authorized web tasks without receiving the
secrets used to log in. Downloads remain available through CloudFiles in the
employee's ordinary browser.

Success means this complete journey works across a restart and a change of
device, with another employee unable to access the first employee's browser,
files, or grants. A passing health endpoint or a component test is insufficient.

## 2. Users, ownership, and boundaries

- Employee: owns the persistent browser profile and files, consents to selected
  credential access, and can withdraw consent or take over a task.
- Hermes: reasons about bounded page state and requests allowed actions and
  login intents for its owner. It has no credential-fetch capability.
- Credential Broker: performs declared login steps deterministically, accesses
  authorized vault material, verifies the application account, and returns
  status only. Grant custody is currently implemented inside this service.
- Operator: installs, qualifies, backs up, restores, and supports an isolated
  installation. Routine support must not require plaintext user credentials.
- Service principal: future separately owned browser and grant for shared
  business automation; never an employee's personal identity.

One persistent profile per principal is a product identity, while a slot is a
temporary allocation of execution capacity. Moving between slots must preserve
the owner's profile and must never transfer state to the next slot occupant.
TinyAuth authenticates at the edge; the internal identity-link service resolves
an immutable PMO principal. Email is display metadata, never ownership authority.

## 3. Required journeys and acceptance

| ID | Outcome | Observable acceptance |
| --- | --- | --- |
| CB-01 | Sign in and obtain a personal workspace | Two employees resolve to distinct principals; simultaneous requests queue fairly when capacity is full; stale sessions cannot reclaim an occupied slot. |
| CB-02 | Return to the same browser | Employee A creates tabs and app state, leaves, employee B uses the slot, then A returns after restart. A recovers only A's state; B never sees it. Repeat with a second slot. |
| CB-03 | Work with Hermes | Hermes discovers/selects an exact tab, navigates, clicks, types ordinary input, and reads useful bounded page state. Unknown or stale tab IDs are rejected. A fresh browser has a supported first-tab path. |
| CB-04 | Watch and take control | A live browser view shows the same tab being automated. User takeover stops conflicting agent input; reconnect and release recover predictably. Agent-visible observation excludes sensitive login material. |
| CB-05 | Grant, log in, and revoke | An authorized user grants selected site/account access. The broker verifies the requested account using Basic Auth or a declared Authentik flow. Revocation prevents new credential use; uncertain outcomes never trigger an automatic duplicate login. |
| CB-06 | Reuse consent safely | After restart, generation change, and tab recreation, an unchanged owner's consent can authorize a fresh, narrowly scoped request. A revoked grant or another owner cannot be rebound. No routine offline reprovisioning per new tab. |
| CB-07 | Complete ordinary forms and MFA | Reviewed form adapters, stored TOTP, and direct human code submission work through broker-only capabilities. Codes are entered into an authenticated user surface, never into an LLM/chat transcript. Unsupported flows return a clear handoff. |
| CB-08 | Retrieve files locally | CloudBrowser download → scan → durable owner area → authenticated CloudFiles listing → local attachment. Validate duplicates, infected files, restart persistence, and cross-owner rejection. |
| CB-09 | Recover access | Crash/recreate restores owner-correct tabs, removes identity state as required by the existing cookie policy, and reauthenticates through the broker when needed. Failure is visible and retries are bounded. |
| CB-10 | Operate a reproducible installation | A clean installation and rollback use qualified images, isolated storage/secrets, and versioned state. Operators can diagnose failures through bounded events without secret disclosure. |

The product preserves useful application sessions where permitted by policy;
it does not promise perpetual authentication. An expired or stripped session is
recovered through a supported login flow or explicit human intervention.

## 4. Mandatory safeguards and operational requirements

- Derive owner/profile/browser/generation/site/tab bindings server-side and
  revalidate them across lifecycle changes and credential use.
- Keep durable user consent separate in meaning from a single request's
  expiring capability. Any implementation change to grant lifetime must retain
  revocation and exact-target checks and include a state migration decision.
- Deny agent access to passwords, OTP seeds/codes, cookies, storage values,
  network bodies, raw CDP, arbitrary evaluation, host files, and processes.
- Vaultwarden remains the credential source of record. Only the deterministic
  broker consumes automated vault-access grants; Hermes cannot browse the vault
  UI, call vault APIs, or obtain access through an unlocked extension or other
  host tools. Enforce this across the actual agent environment, not only its MCP
  tool list. Human noVNC access must not introduce an agent bypass.
- Authorize credential destinations by exact declared origin and redirect
  policy; verify application account identity before reporting authenticated.
- Enforce deadlines across network operations and lock waits. Distinguish
  failure from an unknown outcome, with safe recovery instructions.
- CloudFiles retains the frozen 5 GB per-principal quota, 90-day retention,
  ClamAV scan/quarantine, deletion/erasure workflow, backup/restore, and
  EU-resident backing-storage requirements. A source assertion alone does not
  establish residency or deployed erasure behavior.
- Measure cold/warm activation, recovery time, queue wait, active-slot memory,
  and failed/unknown login outcomes during qualification. Numerical service
  targets must be proposed from measurements before pilot acceptance; no
  unsupported availability or latency commitment is made here.

## 5. Proposed delivery scope

M2a establishes authenticated Hermes public-page control. Minimum M3a live view
and keyboard/mouse takeover precedes M2b application-login acceptance so the
employee can observe and intervene. Edge SSO into CloudBrowser is distinct from
application sign-in inside remote Chromium. Manual sign-in proves the human
path, not broker custody or deterministic account verification. M3b completes
self-service consent. See [viewer foundation](../../../docs/M3-VIEWER-FOUNDATION.md).

The first controlled pilot includes CB-01 through CB-06 and CB-08 through
CB-10 for specifically qualified Basic/Authentik sites. MFA-required sites are excluded until CB-07
is delivered, unless an explicitly tested human takeover completes their flow.
The pilot must include a real viewer, safe ownership across slot reuse, and a
working credential-consent journey. An offline provisioning exercise alone is
a technical qualification, not employee self-service acceptance.

The complete v0.2 product also requires CB-07. Native agent chat, expanded site
coverage, service browsers/CRMOC, and replacement of the prior fleet follow
the personal-browser pilot. Existing external Hermes chat can launch a pilot
task; embedded chat is a later convenience, not a dependency for all work.

## 6. Explicit exclusions

General remote desktop/VDI, replacing the identity provider or Vaultwarden,
cross-client shared browser profiles, arbitrary LLM credential destinations,
automatic support for every website/MFA mechanism, and prior-fleet retirement
without migration acceptance are outside the proposed pilot scope.

## 7. Validation decisions

The proposed roadmap asks Tigo to validate: a complete personal-browser pilot
before CRMOC; the limited initial site set; a real viewer with takeover; and
durable consent with fresh request capabilities. The viewer transport and grant
lifecycle design are bounded design tasks with written decisions before code
changes. They are not silently selected by this PRD.

## 8. Detailed specifications retained

- [Broker PRD](85-credential-broker-prd.md), [boundaries](86-product-boundaries.md),
  and [security model](87-broker-security-model.md): existing detailed requirements.
- [CloudFiles target](89-cloudfiles-product-requirement.md): frozen file requirements.
- [Broker integration](95-w3-1-broker-login-e2e.md) and
  [custody specification](96-granthub-custody-provisioning.md): implementation detail.
- [Contracts](../../contracts/README.md): versioned service interfaces.
- [Approved baseline](../../baselines/v0.2.0/APPROVAL.md): unchanged historical approval.

Where this consolidation resolves ambiguity or proposes a release scope, it is
pending validation; it never silently overrides the approved baseline. Preserve
requirement IDs and update traceability when an approved change is implemented.
