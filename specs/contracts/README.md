# Contracts

Contracts are compatibility surfaces, separate from implementation versions.
Each breaking change increments the contract major version. Additive,
backward-compatible changes use a minor revision documented in the contract.

Current planned surfaces:

- `control-api/v1/` — router and lifecycle control;
- `agent-control/v1/` — restricted page-state/browser actions;
- `credential-broker/v1/` — intent-only login request and status-only result;
- `downloads/v1/` — durable per-owner internal downloads boundary;
- `cloudfiles/v1/` — planned TinyAuth-protected public CloudFiles gateway;
- `events/v1/` — redacted operational/audit events.
