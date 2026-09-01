# Security test plan — baseline v0.2.0

The first implementation tests are expected to start red and establish the
security boundary before extraction from `legacy/`.

## Minimum attack cases

1. Attempt to read or import grant material from the agent surface.
2. Supply a different profile, principal, slot, browser, tab, or origin.
3. Replay a completed request or reuse a stale nonce after reassignment.
4. Select a vault item by display name without an authorized declaration.
5. Send a wildcard/subdomain redirect not present in the declaration.
6. Request an unsupported MFA flow or force a false success result.
7. Cause failures containing passwords, cookies, tokens, page values, or raw
   exceptions and scan logs/audit/model output for leakage.
8. Attempt raw CDP, unrestricted evaluation, filesystem, or process control.
9. Revoke a grant during fetch or rotate a session and verify no stale material
   is accepted.
10. Prove a successful result includes application-level identity verification.

Every case must fail closed, return a bounded status/error code, and leave no
credential-bearing observable.
