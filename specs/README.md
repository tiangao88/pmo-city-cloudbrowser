# CloudBrowser specifications

This directory separates working proposals from approved, immutable baselines.

## Lifecycle

1. Draft changes in `proposals/vX.Y/`.
2. Review requirements, security invariants, contracts, and traceability.
3. Approve material into an immutable `baselines/vX.Y.Z/` snapshot.
4. Tag the corresponding repository commit and container images.
5. Retain both proposal and baseline; do not rewrite an approved baseline.

## Active work

- `proposals/v0.2/` — generic deterministic Credential Broker refactor and
  current W3 status.
- `contracts/` — compatibility-versioned API and event contracts.
- `adr/` — decisions affecting multiple versions or installations.

## Historical import

`archive/pmo-city-builds-w2-w3/` contains the source specifications imported
from the former `pmo-city-builds` component. They are preserved for evidence
and migration traceability. Historical implementation/status claims do not
automatically apply to the new product. Imported source formatting, including
Markdown hard-break whitespace, may be retained; do not normalize it without a
separate provenance decision.
