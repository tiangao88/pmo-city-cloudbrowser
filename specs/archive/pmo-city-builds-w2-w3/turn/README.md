# CloudBrowser TURN relay

## Status

`design-only` — no TURN service has been deployed or connected to the
CloudBrowser fleet.

This package defines the CloudBrowser project's coturn relay for WebRTC media
and data-channel fallback when direct ICE fails on VPN or restrictive networks.
It is kept separate from the fleet Compose because it has a distinct public
UDP/TCP firewall surface and bandwidth failure domain.

## Package

- [`runbook.md`](./runbook.md) — installation and Coolify operating procedure;
- [`specification.md`](./specification.md) — design, capacity and security contract;
- [`compose/compose.yaml.example`](./compose/compose.yaml.example) — Coolify
  raw Docker Compose template;
- [`verification.md`](./verification.md) — positive, negative and recovery checks;
- [`upgrade.md`](./upgrade.md) — image/configuration lifecycle;
- [`rollback.md`](./rollback.md) — rollback procedure;
- [`variables.env.example`](./variables.env.example) — non-secret input inventory;
- [`evidence-template.md`](./evidence-template.md) — sanitized acceptance record;
- [`sources.md`](./sources.md) — upstream and CloudBrowser source record.

The package is part of the CloudBrowser project. It is not a reusable
`/infrastructure` platform runbook or a default Platform composition resource.
