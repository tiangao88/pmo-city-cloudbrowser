# PMO City CloudBrowser

CloudFiles is the TinyAuth-protected, user-scoped file door in the employee's
normal/main browser. Its frozen product target and development plan are in:

- `specs/proposals/v0.2/89-cloudfiles-product-requirement.md`
- `specs/proposals/v0.2/90-cloudfiles-development-plan.md`

CloudBrowser is an independently installable, owner-bound cloud-browser
component for PMO City. It provides persistent Chromium sessions, lifecycle
and queue control, a viewer, restricted agent control, and durable per-user
storage. The target installation platform is a server managed by Coolify.

## Product boundaries

CloudBrowser and the Credential Broker are separate capabilities:

- **CloudBrowser runtime** owns browser lifecycle, slots, profiles, tabs,
  viewer access, queueing, routing, downloads, and restricted browser control.
- **CloudFiles** is the TinyAuth-protected, user-scoped file door in the
  employee's normal/main browser. It lists files downloaded inside CloudBrowser
  and returns them as local-browser attachments; it is not a slot-local API.
- **Credential Broker** is a deterministic, non-LLM service. It obtains
  explicitly authorized Vaultwarden material, fills an owner-bound browser,
  verifies the result, and returns status only.
- **Hermes** requests intent and reasons about page state. It never receives
  passwords, tokens, OTP seeds, cookies, network bodies, or unrestricted CDP.
- **Coolify** installs and operates a pinned release; it is not part of the
  application trust model.

The broker-only custody boundary is an enforced security requirement, not a
convention. Authentik is an adapter, not the definition of the broker.

## Repository navigation

- `specs/` — proposals, immutable baselines, API contracts, ADRs, and the
  imported W2/W3 source material.
- `src/` — product libraries and domain code. Extraction from `legacy/` is
  intentionally test-first.
- `services/` — independently buildable/deployable service entry points.
- `browser/` — extension, browser policy, and image integration material.
- `deploy/coolify/` — reproducible Coolify manifests and release operations.
- `tests/` — unit, contract, integration, security, installation, and E2E
  verification.
- `integrations/` — Hermes and other control-plane adapters.
- `legacy/` — imported implementation and scripts from `pmo-city-builds`,
  retained as migration source and not represented as refactored code.

## Versioning and parallel work

The repository bootstrap is `0.1.0-bootstrap.1`. The first installable product
release will have its own approved specification baseline.

- Work on requirements in `specs/proposals/vX.Y/`.
- Approve material into immutable `specs/baselines/vX.Y.Z/` snapshots.
- Keep compatibility contracts under `specs/contracts/*/vN/`.
- Version code with branches, Git tags, and immutable image digests; do not
  duplicate source trees as `src/v0.1`, `src/v0.2`, and so on.
- Use `release/X.Y` maintenance branches for supported release lines.
- Bind a release manifest to the product version, specification baseline,
  contract versions, component images, and persistent-volume namespace.

This allows different specification proposals and code/release lines to exist
in parallel without silently sharing browser state or rewriting history.

## Coolify installation model

One installation corresponds to one isolated Coolify resource bundle. Every
installation must have unique values for:

- Coolify resource and Compose project name;
- Docker network;
- browser-profile, router-state, grant/broker-state, downloads, and backup
  volumes;
- public browser/files hostnames;
- secret/configuration namespace.

A `v0.1` and `v0.2` installation on the same server must not reuse any of
those resources. Deploy immutable tags and image digests; never use `latest`
for a qualified release. See `deploy/coolify/README.md`.

## Current status

- The repository has been created as a private GitHub repository.
- W2/W3 implementation, tests, deployment references, and specifications have
  been imported from `pmo-city-builds` under explicit `legacy/` and
  `specs/archive/` paths.
- The generic Credential Broker is implemented as the first v0.2 vertical
  slice, including the controlled ordinary form adapter; it is not yet a
  deployable service.
- The v0.2.0-dev1 release now has a digest-pinned, installable manifest after
  runtime image publication and qualification. Coolify deployment, runtime /
  security acceptance, and live-fleet mutation remain Step 19+ work and require
  separate approval.
- The current W3-1 status remains partial: owner-bound recovery passes, while
  strict authenticated-surface continuity through the intended broker path is
  not proven.
- No deployment, restart, credential rotation, or live-fleet mutation is
  performed by this repository bootstrap.

## Development

```bash
uv sync --dev
make check
```

The release is now digest-pinned and installable after image publication and
qualification. Coolify deployment and runtime/security acceptance remain
separate Step 19 work.
