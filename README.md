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

## Current checkpoint

Source checkpoint: `430a066`, 2026-09-11. Broker capabilities, durable grant
custody, Basic/Authentik paths and exact-target page actions are present in
source. Production form mode is disabled. TOTP submission, human code handoff,
a live browser stream, and complete personal-workspace recovery remain open
acceptance work. See the status register for precise evidence.

The current release manifest is pre-build and not installable. Retained image
digests qualify earlier source; they must be rebuilt/qualified and synchronized
before a deployment decision. Local tests do not establish live qualification.

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
