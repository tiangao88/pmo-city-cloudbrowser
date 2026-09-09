# Credential Broker service

The Credential Broker owns deterministic, status-only login execution.

## Current slice (W3-1 broker login E2E)

The service now runs the real status-only broker runtime rather than a
health-only shell. The form and HTTP Basic adapters are wired locally; the SSO
adapter and live image/deployment qualification remain open.

Implemented:

- server-bound intent validation and status-only results;
- deterministic coordinator with a second binding check after credential fetch
  and immediately before adapter execution;
- per-call Vaultwarden unlock (`prelogin → grant → sync → decrypt`), with no
  retained access/refresh token;
- exact-origin form and HTTP Basic adapter dispatch;
- a secret-gated broker-only Basic browser capability using CDP
  `Fetch.authRequired` / `Fetch.continueWithAuth` (not exposed through the
  router/agent-control allowlist);
- bounded idempotency and `cloudbrowser.audit.v1` metadata events with
  credential-shaped payload rejection.

## Remaining gate

SSO/Authentik and MFA live qualification are not included yet. The production
Vaultwarden item, ephemeral browser test slot, image publication, live rollout,
and real login proof remain separately gated before W3-1 can be marked PASS.
