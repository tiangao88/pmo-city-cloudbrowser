# Credential Broker service

The Credential Broker owns deterministic, status-only login execution.

## Current slice (step 13, broker product boundary)

- Status-only intent API via `cloudbrowser.credential_broker.BrokerHttpServer`.
- Server-derived principal binding enforced at the transport boundary
  (PRD-BR-03, S3).
- Deterministic `BrokerCoordinator` that re-resolves the server-side binding
  immediately before fill (PRD-BR-09).
- `cloudbrowser.audit.v1` audit emitter that rejects credential-shaped
  payloads (`password=`, `refresh_token=`, `Authorization: Bearer`, OTP codes).
- Bounded idempotency store keyed by `(principal_id, idempotency_key)`.
- Adapters:
  - `FormLoginAdapter` (existing; bounded selectors, MFA reporting,
    application-identity verification).
  - `BasicAuthAdapter` (PRD-BR-04; HTTPS-only, exact origin, no URL
    credentials, declared redirects only).
  - `TOTPAdapter` (PRD-BR-06; broker-owned RFC 6238 SHA-1 6-digit code).
  - `HumanHandoffStore` (PRD-BR-06 chat-ask path; one-shot opaque token,
    no code retention or return).

## Public surface

```python
from cloudbrowser.credential_broker import (
    AuthenticatedPrincipal,
    BrokerCoordinator,
    BrokerHttpServer,
    ServerIdentity,
)
```

## Out of scope (status-only)

The current slice is status-only and never returns credentials to the agent.
Real Microsoft/Authentik connector wiring, durable Vaultwarden session
acquisition, and the production `grant-sync` migration remain W3-13 deferred
work pending explicit Tigo approval and migration path sign-off.
