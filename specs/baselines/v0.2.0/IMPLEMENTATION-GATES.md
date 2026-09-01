# v0.2 contract implementation gates

These tests are the first implementation deliverable for baseline `v0.2.0`.
They intentionally target the public security and contract surfaces rather than
legacy implementation details.

## Credential Broker

- status is a closed enum and never contains credential material;
- request binding is server-derived and cannot be caller-overridden;
- site declarations use exact origins and explicit redirect allowlists;
- unsupported or ambiguous MFA fails closed;
- revocation, stale nonce, owner mismatch, and slot reassignment fail closed;
- success requires application identity verification.

## Agent control

- forbidden capability names are rejected;
- cookie/storage values, network bodies, authorization headers, password
  values, raw CDP, unrestricted evaluation, filesystem, and process control are
  not exposed;
- browser control is limited to the authenticated principal's browser.

## Operational boundary

- audit records are metadata-only and redacted;
- no service imports the legacy slot-side vault client;
- new service code is not copied from `legacy/` without a failing test first.

The initial red tests should be added under `tests/contract/` and
`tests/security/` before production code is extracted.
