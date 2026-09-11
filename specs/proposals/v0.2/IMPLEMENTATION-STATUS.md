# CloudBrowser implementation status

Evidence checkpoint: **2026-09-11**, `main` at
`430a06603e8dff9531cc14042a01e38fff2b8874` (`feat(broker): integrate secure
credential login flow`). Remote was fetched and matched the handoff. The last
change touches 135 files; the handoff says it was pushed directly to main,
without a completed final independent review.

## Evidence vocabulary

- **Source present**: implementation and referenced tests are in this commit.
- **Locally verified**: a dated run in the current takeover environment.
- **Image qualified**: image digest/provenance and runtime checks tied to a SHA.
- **Deployed/accepted**: named environment and dated complete-user-journey proof.
- **Historical report**: prior documentation or handoff, not freshly verified.

Never collapse these states into an unqualified "done". Current source has no
matching qualified release in the checked-in manifest. Live systems were not
inspected during the initial documentation reset. Subsequent read-only
environment verification on 2026-09-11 is recorded in
[M0 environment evidence](../../../docs/evidence/2026-09-11-m0-environment.md).

## M1 source increment — 2026-09-11

Tigo authorized M1 implementation on `feat/m1-owner-continuity`. Stable
principal/profile storage, same-volume exclusive leases, graceful Chromium
session shutdown/native restore, and owner-specific download routing are now
implemented. Explicit durable consent survives slot/generation/tab changes while
each broker authorization remains bound to the current exact request. Prior
exact grants are not widened automatically.

The synthetic real-Chromium A → B → A / second-slot test proves tabs, application
cookies, local storage and downloads without transferring Alice's state to Bob.
Final Linux qualification at `37e50c6`: **1030 passed, 3 intentionally disabled
form cases skipped**; all six validators and **80 CloudFiles boundary cases**
passed. See [M1 evidence](../../../docs/evidence/2026-09-11-m1-continuity.md).
These are source results, not live acceptance.
See [ADR-0005](../../adr/0005-m1-personal-state-and-consent.md) and the
[migration/recovery checklist](../../../docs/M1-MIGRATION.md).

## M2 source increment — 2026-09-11

Tigo authorized M2 on `feat/m2-first-browser-task`. `tab_open` now supplies a
bounded first target for a fresh browser; all subsequent page actions retain an
exact Chromium target. The browser rechecks the current principal/generation
inside its serialized action gate, so a lease rotation cannot race between an
agent-control precheck and the page side effect.

The supported Hermes entrypoint is now the `cloudbrowser-hermes-mcp` local stdio
bridge. It exposes eight bounded tools through the authenticated viewer surface
and replaces the old supported-tree helper that bypassed the router through raw
CDP. Hermes' installed MCP SDK completed initialization/tool discovery.

Final Linux qualification at `184d4bc`: **1065 passed, 3 intentionally disabled
form cases skipped**; all six validators and **80 CloudFiles boundary cases**
passed. The focused real-browser, Basic/Authentik, wrong-origin/account,
idempotency and MCP suite passed **96 cases**. See
[M2 evidence](../../../docs/evidence/2026-09-11-m2-browser-task.md). These are
source results, not an image, deployment, real-site or employee acceptance.

## Capability inventory

| Capability | Source evidence | Remaining acceptance |
| --- | --- | --- |
| Immutable identity and authorization | `edge_auth.py`, `identity_link_service.py`, `identity_links.py`; identity/security tests | Current deployed edge-to-principal proof for two employees. |
| Queue, activation, leases, roster, leave | `router/sessions.py`, `router/router_api.py`; router contract tests | Integrated multi-slot and fresh-browser journey; current deployment capacity unverified. |
| Browser lifecycle and profile | `browser_slots/browser_process.py`, `supervisor.py`, `lifecycle.py`, `owner_storage.py`; M1 real-Chromium continuity test | Source ownership/clean-restart continuity proven synthetically; uncertain crash locks need operator recovery. Live migration and multi-slot deployment remain qualification work. |
| Exact-target agent actions | `browser_slots/page_actions.py`, `agent_control.py`; M2 first-tab and real-browser task tests | `tab_open`, navigate, click, type, page_info and tabs_list passed the synthetic real-Chromium task. Useful real-site acceptance and richer bounded observation remain separate. |
| Hermes entrypoint | `hermes_mcp.py`, `integrations/hermes/cloudbrowser/`; MCP contract/security tests and Hermes SDK probe | Eight mediated stdio MCP tools are source-qualified. An isolated stopped `cloudbrowser-test` profile is installed on mother01 with no copied secrets; distinct TinyAuth-compatible auth, bridge enablement and hosted task acceptance remain open. Interactive OIDC renewal is not implemented. |
| Viewer | `viewer/session_surface.py`, `viewer/__init__.py` | Authenticated queue/control HTML exists; live video/streaming and human takeover remain missing product work. |
| Broker authorization | `credential_capability.py`, `router/credential_broker_forwarder.py`, broker coordinator/nonce/idempotency/deadline modules | Post-remediation review and real-browser/site acceptance of replay, races, unknown outcomes and deadlines. |
| Grant custody | `credential_broker/grant_custody.py`, `grant_admin.py`, `runtime.py`; M1 consent tests | Explicit durable consent and fresh exact-target authorization implemented. Employee self-service capture remains M3; independent security review and live acceptance remain open. |
| Basic and Authentik | Broker adapters, `browser_slots/basic_auth.py`, `authentik.py`; real-CDP and fixture tests | Synthetic current-source exact-origin/application-account checks passed. Current-source image and approved live-site proof remain open; Authentik detects MFA but has no production TOTP/code submission. |
| Ordinary form and MFA | Form/TOTP/handoff components/tests exist | Production form mode is disabled; 3 historical form integration tests intentionally skipped. Production TOTP submission and human one-time-code handoff are unavailable. |
| CloudFiles | `cloudfiles/`, `downloads/`, browser ingest, identity service, Compose wiring and E2E tests | Requalify actual browser → scan/store → public gateway → local attachment with current images, persistence and two owners. |
| Release | `deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml` | `installable: true`, `sourceState: qualified`, `imageState: qualified`. Nine immutable digests qualify `ce0ef5d`, workflow run `34594208145`; live deployment and user acceptance are recorded separately. |

## Product/implementation mismatches requiring decisions

1. **Profile ownership versus slot ownership — M1 source decision made.**
   Production selects stable owner directories, holds an exclusive lease, and
   restores native tabs. Unattributed old data is preserved but never adopted
   automatically; rollout must follow the migration checklist.
2. **Consent lifetime versus request lifetime — M1 source decision made.**
   Explicit stable consent resolves fresh exact-target authorizations; old
   grants remain narrow. Offline reprovisioning requires prior scope revocation.
   Employee self-service remains a separate product journey.
3. **A page-control shell versus the promised viewer.** Control endpoints and
   bounded DOM actions exist; they do not deliver a live shared browser view.
4. **Source progress versus release progress.** The latest commit advances SSO,
   custody, and click/type beyond older READMEs. It simultaneously invalidates
   the earlier images as evidence for current source. Neither direction may be
   inferred from old "shipped" headings.
5. **Fresh-tab and useful page-state path — M2 source decision made.**
   `tab_open` creates one bounded HTTP(S) target and returns its exact opaque ID.
   A real-Chromium synthetic task covers open, type, click, page state, listing
   and stale-target rejection. Capture still rejects page bodies exceeding 4096
   bytes rather than truncating them; broader observation design remains open.
6. **Development environment reproducibility.** Native crypto expects Linux
   library names, and the Authentik real-Chrome fixture pins a previous agent's
   absolute executable path. M0 must make the qualified test environment
   reproducible; installing a browser somewhere else does not satisfy that gate.

## Verification record

Handoff report for `430a066`: `uv run make check` **1006 passed, 7 skipped**;
CloudFiles boundary **80 passed**; compileall and diff checks clean. Four skips
were missing Compose CLI and three were deliberately disabled production form
tests. These are reported prior results, not this takeover's verification.

Current takeover run on macOS/Python 3.12.12:

- All six repository validators passed (specification, sensitive files,
  release manifest, installation, image inputs and image workflow).
- Full suite: **969 passed, 30 failed, 7 errors, 7 skipped**. The native crypto
  loader attempts Linux `libcrypto.so.3`/`libcrypto.so`, unavailable on this
  Mac; crypto/custody tests therefore cannot establish a green native baseline.
  The file special-entry test separately failed with `AF_UNIX path too long`.
- The file-path failure was reproduced in isolation and resolved for verification
  by a short pytest temporary directory, without changing production code or
  test assertions. The documentation/layout/contract selection plus all 80
  CloudFiles boundary cases then passed: **97 passed**.
- Current skips are 3 intentionally disabled form tests and 4 real-Chrome tests
  whose executable discovery did not find Chrome. Unlike the handoff run, the
  Compose rendering checks ran here. These skip sets are not interchangeable.
- Final documentation verification: **17 documentation/layout/contract checks
  passed**, all six validators passed, and `git diff --check` passed.
  Relative-link inspection found no newly broken links; 14 unchanged historical
  links in `design-proposal.md` refer to material absent from this repository.

M0 retains Linux/OpenSSL and real-Chromium qualification as an open gate; this
Mac run does not reproduce the handoff's green full suite. Documentation changes
do not repair or waive that gate.

### Subsequent Linux baseline verification — 2026-09-11

The original Hermes environment reproduced **1006 passed, 7 skipped** at
`430a066`. A separate persistent Linux checkout then verified the Mac's
documentation candidate `3eb071a` with the missing Compose executable supplied:
**1010 passed, 3 intentionally disabled form tests skipped**, all six validators
passed, CloudFiles boundary **80 passed**, compileall/diff checks passed.
This closes the environment/test reproduction gate noted above. The original
Hermes checkout stayed clean and unchanged.

All nine deployed application image references match the manifest's older pins
attributed to `50ce198`; none establish qualification of `430a066`. See
[evidence](../../../docs/evidence/2026-09-11-m0-environment.md) and
[development workflow](../../../docs/DEVELOPMENT.md).

A final independent security GO verdict, current-source image qualification,
and live acceptance are not supplied by this documentation review.

## Documentation ownership

[PRODUCT-PRD.md](PRODUCT-PRD.md) owns proposed product outcomes;
[ROADMAP.md](ROADMAP.md) owns proposed next work; this file owns current evidence.
Service READMEs explain their implementation and configuration. Contracts own
interfaces. Numbered proposals retain detailed requirements and historical
plans. Approved baselines and imported evidence are preserved unchanged.
The older durable plan and W3 register remain historical indexes with links here.
