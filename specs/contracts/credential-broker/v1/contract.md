# Credential Broker API v1

This contract defines the status-only broker boundary for baseline `v0.2.0`.
The request is an intent; it is not a credential transport.

## Request: two distinct HTTP boundaries

Implementation clarification for source `430a066`: the logical intent is
translated by the authenticated router into a private broker capability.

The caller sends `POST /v1/credential/login` to the router with:

```json
{
  "request_id": "opaque-request-id",
  "site_id": "declared-site",
  "target_tab_id": "exact-owner-tab"
}
```

The router derives the active session/profile/principal/browser/generation.
It mints a signed, expiring capability with site, exact target, operation,
request correlation, audience, deployment and one-time nonce. Caller-supplied
credential/account references, alternate binding fields and extra fields are
rejected. An exact target is mandatory, not an optional first-tab fallback.

The router sends `POST /v1/credential/login` to the private broker with only
`{"capability": "<signed one-time capability>"}`. The capability is not
returned as an agent handle. The broker verifies it, resolves principal-scoped
grant custody, and enforces durable nonce/idempotency state and live binding.
It does not accept the earlier username-reference or shared bearer schema.

Reference implementations: `router/router_api.py`,
`router/credential_broker_forwarder.py`, `credential_capability.py`, and
`credential_broker/api.py` under `src/cloudbrowser/`.

## Site declaration

A declaration is versioned and immutable for the request. It specifies the exact
origin, explicit redirect origins, adapter version, entry path, field roles,
success/failure assertions, MFA policy, timeout, retries, and handoff policy.
Wildcard and subdomain matching are denied unless explicitly declared.

## Response

```json
{
  "request_id": "opaque-server-id",
  "status": "authenticated",
  "error_code": null,
  "duration_ms": 1234
}
```

`status` is one of `authenticated`, `mfa_required`, `failed`, `not_shared`, or
`unsupported`. `error_code` is non-sensitive and bounded. Responses must never
contain passwords, tokens, cookies, storage values, DOM values, network bodies,
raw exception text, screenshots, or grant contents.

## Failure rules

Owner mismatch, profile mismatch, stale nonce, slot reassignment, revoked grant,
ambiguous destination, unsupported MFA, failed verification, or infrastructure
uncertainty returns a bounded non-success status and performs no permissive
fallback.

Application identity verification is required before `authenticated` is
returned.
