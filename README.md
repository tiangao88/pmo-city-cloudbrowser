# PMO City CloudBrowser

CloudBrowser gives each employee a persistent personal Chromium workspace on
client infrastructure, accessible through company sign-in and controllable by
their Hermes agent. A deterministic Credential Broker handles authorized logins
without exposing credentials to the agent. CloudFiles returns browser downloads
to the employee's ordinary browser.

## Start here

- [Product PRD](specs/proposals/v0.2/PRODUCT-PRD.md): intended journeys,
  requirements, scope and acceptance.
- [Development roadmap](specs/proposals/v0.2/ROADMAP.md): proposed milestones,
  dependencies and release gates, awaiting Tigo's validation.
- [Implementation status](specs/proposals/v0.2/IMPLEMENTATION-STATUS.md):
  source evidence, gaps, test results and qualification state.
- [Service map](services/README.md): implementation responsibilities.
- [Installation guide](deploy/coolify/README.md): configuration and operation.
- [Development workflow](docs/DEVELOPMENT.md): edit on the Mac and test exact
  commits in the separate persistent Linux checkout on mother01.

## Current checkpoint

Qualified runtime source checkpoint: `2e300ef`, 2026-09-11. M1 owner
continuity and M2's fresh-browser exact-tab task, Basic/Authentik synthetic
qualification, mediated Hermes stdio MCP entrypoint and restart recovery are
present in source. The latest CI gate is **1078 passed, 7 skipped**; the
skips are four unavailable Compose-CLI checks in that isolated environment and
three deliberately disabled production-form cases. See the
[M2 evidence](docs/evidence/2026-09-11-m2-browser-task.md) and status register
for the precise boundary.

The digest-pinned release is healthy on `cloudbrowser2.dev01.pmo.city`. An
isolated authenticated Hermes profile passed the bounded start, list, open and
exact-tab inspection journey. Production form mode is disabled; TOTP
submission, human code handoff, crash-time open-tab continuity, a live browser
stream/takeover and interactive Hermes OIDC renewal remain open. The independent
broker/security verdict also remains a separate gate.

The current release manifest is image-qualified and installable. Its nine
immutable image digests qualify source commit `2e300ef` in CI run
`34623825124`; release commit `b6fc6e1` synchronizes those pins. Image
qualification and the bounded authenticated dev01 acceptance are recorded as
separate evidence.

Page reading returns a marked, UTF-8-safe excerpt when visible text exceeds
4096 bytes. Known backend action errors are preserved through the router.

## Product boundaries

- Runtime: browser lifecycle, temporary slots, persistent profiles, routing,
  queueing, viewer and restricted agent control.
- Credential Broker: authorized Vaultwarden access and deterministic,
  exact-target login with status-only results. Grant custody belongs here.
- CloudFiles: authenticated per-user file listing and local attachment retrieval;
  the downloads service remains internal.
- Hermes: owner-scoped page actions and login intents; no passwords, tokens,
  OTP seeds/codes, cookies, network bodies or unrestricted CDP.
- TinyAuth/identity-link: edge authentication and immutable principal resolution.
- Coolify: installation and operation of isolated, digest-pinned service bundles.

## Repository layout and documentation rules

`src/cloudbrowser/` contains runtime code; `services/` contains entrypoints
and images; `browser/` contains browser assets; `integrations/` contains
adapters; `tests/` and `tools/` contain verification.

`specs/proposals/v0.2/` holds mutable requirements and the current planning
entrypoints. `specs/contracts/` holds versioned APIs. `specs/baselines/`
holds immutable approvals. `specs/archive/` and `legacy/` preserve prior
specifications and implementation as historical evidence.

The PRD records requirements, the roadmap records intended work, and the status
register records demonstrated behavior. Source, image, deployment and user
acceptance are separate evidence. Historical documents cannot establish current
readiness. Changes to approved requirements need a proposal and new approval;
approved baselines are never rewritten.

## Development and release

```bash
uv sync --dev
uv run make check
uv run make cloudfiles-boundary
```

Follow [CONTRIBUTING.md](CONTRIBUTING.md). Each installation has its own
resource/project name, network, profiles/state/download volumes, public hosts
and secrets. Versions must not share persistent state. Qualify all nine service
images against a recorded source SHA, use immutable digests, and follow the
[release guide](deploy/coolify/releases/README.md) for migration and rollback.
