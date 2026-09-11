# CloudBrowser implementation status

Evidence checkpoint: **2026-09-11**. The takeover baseline was `main` at
`430a06603e8dff9531cc14042a01e38fff2b8874`. Current M2 work is on the unmerged
branch `feat/m2-first-browser-task`; its latest qualified runtime source is
`2e300ef` and its release pin metadata is `b6fc6e1`.

## Evidence vocabulary

Sequencing update, approved 2026-09-11: the accepted bounded task is **M2a**.
Full M2 is not complete. M3a minimum live viewer/takeover precedes M2b application
login; M3b completes self-service consent. No live viewer is delivered by this
planning change. See [viewer foundation](../../../docs/M3-VIEWER-FOUNDATION.md).

Review target `9c11358710bc9d16f7b32d25e27c0f4434d20985` remains frozen. Scan
`f6547962-81de-4748-bede-39f6e240eb82` is unfinished after a platform check
stopped a worker. Candidate observations are not validated findings or a GO
verdict. Preserve that scan; viewer work does not replace its release gate.

Additional Linux qualification at `b6fc6e1`: **1082 passed, 3 intentionally
disabled production-form skips**, all six validators passed; focused
security/login/browser suite: **176 passed**. Runtime and tests are identical
to the review target (intervening changes are documentation). The Mac full run
did not pass, including unavailable Linux OpenSSL dependency; Linux remains the
qualification target. These results supplement the historical CI evidence.

Read-only deployment check: broker uses `basic-local`/Basic, with no Authentik
entry or identity-proof configuration. Both manifests omit initial agent-control
bindings that the running container supplies externally. Source-compose viewer
also omits the router URL required when enabling edge auth. Clean-install parity
and end-to-end login timeout alignment remain follow-ups, not accepted behavior.

- **Source present**: implementation and referenced tests are in this commit.
- **Locally verified**: a dated run in the current takeover environment.
- **Image qualified**: image digest/provenance and runtime checks tied to a SHA.
- **Deployed/accepted**: named environment and dated complete-user-journey proof.
- **Historical report**: prior documentation or handoff, not freshly verified.

Never collapse these states into an unqualified "done". Live systems were not
inspected during the initial documentation reset. Subsequent environment
verification is recorded in [M0 environment evidence](../../../docs/evidence/2026-09-11-m0-environment.md),
and the later M2 source/image/deployment/acceptance proof is recorded below.

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
exact Chromium target. The browser rechecks principal/generation inside its
serialized action gate. This component control does not establish end-to-end
race freedom; that claim remains subject to the unfinished independent review.

The supported Hermes entrypoint is now the `cloudbrowser-hermes-mcp` local stdio
bridge. It exposes eight bounded tools through the authenticated viewer surface
and replaces the old supported-tree helper that bypassed the router through raw
CDP. Hermes' installed MCP SDK completed initialization/tool discovery.

Acceptance added non-root download-volume preparation, active-session bridge
recovery, exclusive-lease-aware Chromium singleton recovery, browser-only
restart reconciliation and bounded router forwarding of tab listings. Final
runtime source `face98a` passed the complete Linux gate: **1074 passed, 7
skipped**, with all six validators green. GitHub Actions run `34610008200`
built and qualified all nine images; `34246d2` pins their immutable digests.

The release is `running:healthy` behind `cloudbrowser2.dev01.pmo.city`. The
isolated authenticated `cloudbrowser-test` Hermes profile successfully started
the session, listed tabs, opened `https://example.com/`, and inspected the exact
returned tab as `Example Domain`; a model-driven MCP one-shot also passed. See
[M2 evidence](../../../docs/evidence/2026-09-11-m2-browser-task.md). Live
application credentials, Vault grants and MFA remain outside this acceptance.

## Capability inventory

Latest M2 follow-up: `2e300ef` / CI `34623825124` / release `b6fc6e1` passed
1078 tests (7 explained skips), image qualification and dev01 deployment. The
dashboard bridge reads a marked 4096-byte excerpt from `pmo.city` successfully
and preserves `browser_unavailable` for a stale tab. The roster now labels
missing display metadata accurately; expiry of abandoned waiting records remains
open. This supersedes the earlier runtime references in the inventory below.

| Capability | Source evidence | Remaining acceptance |
| --- | --- | --- |
| Immutable identity and authorization | `edge_auth.py`, `identity_link_service.py`, `identity_links.py`; identity/security tests | Current deployed edge-to-principal proof for two employees. |
| Queue, activation, leases, roster, leave | `router/sessions.py`, `router/router_api.py`; router contract tests | Integrated multi-slot and fresh-browser journey; current deployment capacity unverified. |
| Browser lifecycle and profile | `browser_slots/browser_process.py`, `supervisor.py`, `lifecycle.py`, `owner_storage.py`; M1 real-Chromium continuity and M2 restart tests | Stable ownership, clean restart, stale singleton recovery and browser-only binding reconciliation are implemented and dev01-tested. Abrupt-crash tab continuity and multi-slot live qualification remain open. |
| Exact-target agent actions | `browser_slots/page_actions.py`, `agent_control.py`, `router/router_api.py`; M2 browser/forwarding tests | The authenticated Hermes dev01 task passed `tab_open`, `tabs_list` and exact-target `page_info`. Richer bounded observation and approved application-site acceptance remain separate. |
| Hermes entrypoint | `hermes_mcp.py`, `integrations/hermes/cloudbrowser/`; MCP contract/security tests and Hermes SDK probe | Eight mediated stdio MCP tools are source-qualified, enabled and accepted in the isolated authenticated `cloudbrowser-test` profile. Interactive OIDC acquisition/renewal is not implemented. |
| Viewer | `viewer/session_surface.py`, `viewer/__init__.py` | Authenticated queue/control HTML exists; live video/streaming and human takeover remain missing product work. |
| Broker authorization | `credential_capability.py`, `router/credential_broker_forwarder.py`, broker coordinator/nonce/idempotency/deadline modules | Post-remediation review and real-browser/site acceptance of replay, races, unknown outcomes and deadlines. |
| Grant custody | `credential_broker/grant_custody.py`, `grant_admin.py`, `runtime.py`; M1 consent tests | Explicit durable consent and fresh exact-target authorization implemented. Employee self-service capture remains M3; independent security review and live acceptance remain open. |
| Basic and Authentik | Broker adapters, `browser_slots/basic_auth.py`, `authentik.py`; real-CDP and fixture tests | Synthetic current-source exact-origin/application-account checks passed. Current-source image and approved live-site proof remain open; Authentik detects MFA but has no production TOTP/code submission. |
| Ordinary form and MFA | Form/TOTP/handoff components/tests exist | Production form mode is disabled; 3 historical form integration tests intentionally skipped. Production TOTP submission and human one-time-code handoff are unavailable. |
| CloudFiles | `cloudfiles/`, `downloads/`, browser ingest, identity service, Compose wiring and E2E tests | Requalify actual browser → scan/store → public gateway → local attachment with current images, persistence and two owners. |
| Release | `deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml`; M2 deployment evidence | `installable: true`, `sourceState: qualified`, `imageState: qualified`. Nine immutable digests qualify `face98a`, workflow run `34610008200`; the pinned stack is healthy and the bounded authenticated Hermes journey passed on dev01. |

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
4. **Source progress versus release progress.** M2 runtime source `face98a` is
   image-qualified and deployed by immutable digest; `34246d2` records those
   pins. Container health and authenticated journey acceptance are recorded as
   distinct checks even though both now pass for the bounded M2 task.
5. **Fresh-tab and useful page-state path — M2 source decision made.**
   `tab_open` creates one bounded HTTP(S) target and returns its exact opaque ID.
   A real-Chromium synthetic task covers open, type, click, page state, listing
   and stale-target rejection. The page-reading follow-up now returns a bounded
   4096-byte UTF-8 excerpt with an explicit truncation marker for larger pages;
   pagination and broader observation design remain open.
6. **Development environment reproducibility.** The dedicated Linux checkout
   is the authoritative full-suite environment and is reproducible without
   changing the original Hermes workspace. The Mac remains suitable for source
   work and focused tests but does not expose Linux's `libcrypto.so` name.

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

The statement above describes the initial M0 inspection. It is superseded for
M2 by the `face98a` / run `34610008200` qualification and `34246d2` deployment
record. See [M2 evidence](../../../docs/evidence/2026-09-11-m2-browser-task.md)
and [development workflow](../../../docs/DEVELOPMENT.md).

A final independent broker/security GO verdict and live credential/MFA
acceptance remain separate open gates.

## Documentation ownership

[PRODUCT-PRD.md](PRODUCT-PRD.md) owns proposed product outcomes;
[ROADMAP.md](ROADMAP.md) owns proposed next work; this file owns current evidence.
Service READMEs explain their implementation and configuration. Contracts own
interfaces. Numbered proposals retain detailed requirements and historical
plans. Approved baselines and imported evidence are preserved unchanged.
The older durable plan and W3 register remain historical indexes with links here.
