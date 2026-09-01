# Credential Broker API v1

This contract defines the status-only broker boundary for baseline `v0.2.0`.
The request is an intent; it is not a credential transport.

## Request

A broker request contains only:

- `request_id` or a server-bound nonce;
- authenticated profile context (server-derived);
- authenticated principal context (server-derived);
- server-resolved owner browser and optional owner tab;
- an allowlisted `site_id` or exact declared origin;
- an account selector/reference, never a password or token;
- optional idempotency key.

The caller cannot select another profile, principal, slot, browser, grant, or
origin by supplying an alternate value.

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
