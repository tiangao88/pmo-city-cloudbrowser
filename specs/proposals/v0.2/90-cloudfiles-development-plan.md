# CloudFiles development plan

> Version: **v0.2 development proposal — 2026-09-03**
> Status: **RECOMMENDED PLAN — follows the frozen CloudFiles target**
> This plan describes implementation gates. It does not authorize live
> deployment or fleet mutation.

## How to read this plan

**Phase 0 is the pre-implementation definition and safety gate.** It is not a
service, a deployment step, or a hidden coding phase. Its purpose is to settle
what the public CloudFiles surface means, define the trust boundaries, and
write security tests that fail before production code exists.

Current position as of 2026-09-03:

- **Done:** the product target is frozen in `89-cloudfiles-product-requirement.md`;
  this development plan is committed; the `cloudfiles/v1` public contract is
  drafted; and the existing `downloads/v1` internal contract is identified.
- **Remaining in Phase 0:** review/approve the public contract, complete the
  route/threat matrix, and add and observe the focused security tests failing.
- **Not started:** Phase 1 production implementation.

The issue list in §7 is grouped by phase. The correct dependency order is
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → local E2E/release
qualification → explicitly approved live deployment.

## 1. Development decision

Build CloudFiles as a new product slice in the new repository. Do **not** copy
the old `downloads-api.py`, old router, or old slot-local filesystem behavior
into production code.

Use the old repository only for:

- product requirements and UX evidence;
- compatibility behavior that is explicitly retained;
- security/regression cases that must be preserved;
- migration and rollback reference.

The new implementation must keep the existing service boundaries: a public
CloudFiles gateway, an internal owner-bound downloads service, and a browser
ingest adapter. TinyAuth remains an edge authentication mechanism, not a
substitute for service authorization.

## 2. Target code structure

Proposed layout:

```text
src/cloudbrowser/
  cloudfiles/
    contracts.py       # public request/response DTOs and error codes
    identity.py        # authenticated principal/binding abstraction
    policy.py          # authorization and route policy
    filenames.py       # flat-name validation and collision allocation
    templates.py       # escaped HTML shell; no business logic
    gateway.py         # public CloudFiles application/use cases
    ingest.py          # browser-download ingest port and orchestration
    retention.py       # quota, age policy, purge decisions
    quarantine.py      # scan result and quarantine policy
    ports.py            # storage/scanner/clock/identity protocols
    service.py         # application orchestration
    api.py              # bounded HTTP adapter only
  downloads/
    ...                # existing internal downloads/v1 contract

services/
  cloudfiles/
    README.md
    Dockerfile
    entrypoint.py       # configuration + dependency wiring only
  downloads/
    ...                # existing internal service entrypoint

browser/
  downloads/
    ...                # Chromium download-directory/injest adapter

tests/
  unit/cloudfiles/
  contract/cloudfiles/
  security/cloudfiles/
  integration/cloudfiles/
  e2e/cloudfiles/
```

The exact module names may change during implementation, but the ownership
rules should remain: HTTP adapters contain no storage policy, templates contain
no identity decisions, and the browser adapter cannot choose another principal.

## 3. Boundary design

### 3.1 Public CloudFiles gateway

The gateway owns the employee-facing HTTP surface:

- authenticated `GET /` HTML page;
- authenticated `GET /api/files` listing;
- authenticated `GET /file/<name>` attachment response;
- bounded `/health` and `/ready` behavior;
- translation of edge identity into an internal server-derived binding;
- safe response headers, cache policy, and request correlation.

The gateway is the only public target. The downloads container is not exposed
as a public host.

### 3.2 Internal downloads service

The existing `downloads/v1` service remains the protected data boundary. The
gateway calls it through a typed client/port that supplies:

- `X-CB-Trusted-Secret` from server configuration;
- server-derived principal/profile/browser/generation headers;
- a fresh bounded request ID.

The internal service continues to enforce owner isolation independently of the
gateway. A gateway bug must not become a cross-owner file read.

### 3.3 Browser ingest

Implement a separate ingest port rather than coupling storage code to Chromium
or the old slot process. The browser/slot supervisor emits a bounded download
completion event or invokes a local ingest client with:

- server-derived binding;
- source filename and bounded source handle/stream;
- content length and checksum where available;
- request/event ID.

The ingest service allocates the final safe name, scans before publication, and
atomically publishes only clean content into the owner area. It must never
accept a caller-selected owner path.

### 3.4 Authentication and identity

TinyAuth authenticates the public request and enforces `PMOC_Users` at the
edge. The gateway must validate the trusted ingress configuration and map the
authenticated subject to the immutable PMO principal. Do not make the public
service trust an arbitrary `Remote-Email` header.

The identity mapping should be an explicit interface so tests can use a fake
server-backed binding and production can later use the approved PMO identity
provider. If the identity is missing, ambiguous, revoked, or stale, fail closed.

## 4. Delivery sequence

Each phase follows RED → GREEN → REFACTOR. No production implementation is
written before its focused test is observed failing.

### Phase 0 — contract and threat model

- Approve this requirement and plan as the v0.2 working proposal.
- Define `cloudfiles/v1` public contract separately from `downloads/v1`.
- Define identity, gateway-to-downloads, ingest, scanner, retention, and
  deletion ports.
- Write the threat model and route/response matrix.
- Write failing security tests for forged identity, cross-owner access,
  traversal, header injection, direct-downloads exposure, and unauthenticated
  routes.

**Exit:** public and internal contracts are versioned; all boundary tests have
been seen red.

### Phase 1 — pure domain and storage policy

- Implement safe filenames and deterministic duplicate-name allocation.
- Implement owner-key derivation and storage path confinement.
- Implement bounded metadata, quota calculation, retention selection, and
  deletion/quarantine decisions.
- Use injected clock, filesystem/storage port, and scanner port.
- Add property-style/table-driven tests for adversarial filenames and owner
  isolation.

**Exit:** domain tests are green without an HTTP server, Chromium, TinyAuth, or
Coolify.

### Phase 2 — internal ingest and downloads integration

- Implement clean-file ingest with temporary-file permissions, size limits,
  scan-before-publish, and atomic rename.
- Preserve quarantined material outside the retrievable entries namespace.
- Add a typed client for `downloads/v1` and contract tests for trusted headers,
  timeout, bounded errors, and request IDs.
- Connect the browser download completion seam using a fake event source first.

**Exit:** a test can ingest a file for owner A, list/read it, reject infected
content, and prove owner B cannot access it.

### Phase 3 — public CloudFiles gateway

- Implement the HTML list using escaped metadata and a stable, minimal
  template.
- Implement authenticated listing and attachment routes.
- Add security headers, `Content-Disposition: attachment`, content-type
  allowlisting, bounded response sizes, and no-store policy for owner data.
- Ensure `/health` is the only intentionally unauthenticated public route;
  define `/ready` explicitly before exposing it.
- Keep TinyAuth labels/domain configuration in deployment documentation and
  infrastructure manifests, not in application authorization code.

**Exit:** a full local HTTP test reproduces the employee journey: authenticate,
see only owner A's file, and receive bytes as a local-browser attachment.

### Phase 4 — lifecycle, operations, and data guarantees

- Add 5 GB quota enforcement per principal.
- Add 90-day retention janitor with dry-run and auditable redacted results.
- Add GDPR erasure workflow with idempotency and verification.
- Add ClamAV adapter behind the scanner port and quarantine notification seam.
- Add durable-volume checks, backup/restore documentation, EU residency
  assertion, metrics, readiness dependency checks, and safe operator runbooks.

**Exit:** restart/recreate, retention, quota, quarantine, and erasure tests are
green; operational failure modes fail closed without leaking file data.

### Phase 5 — deployment and live qualification

Only after all source and image gates pass:

- build the dedicated `cloudfiles` image as a non-root service;
- publish with provenance/SBOM and digest pinning;
- add it to the release manifest and compose network;
- configure the existing Coolify service's Domains entry for the public host;
- apply TinyAuth edge configuration through the approved service-scoped path;
- run persistence, isolation, authenticated-binding, rollback, and local
  download qualification.

Deployment, DNS, Traefik, TinyAuth, or live-fleet changes require separate
explicit approval. This document does not grant that approval.

## 5. Tests and acceptance matrix

Required test layers:

- **Unit:** filename, allocation, owner key, quota, retention, quarantine,
  response headers, template escaping.
- **Contract:** `cloudfiles/v1`, `downloads/v1`, identity binding, ingest event,
  scanner, retention, and deletion ports.
- **Security:** forged `Remote-Email`, forged owner headers, traversal,
  symlink races, hidden/quarantine names, CR/LF injection, oversized files,
  cross-owner reads, replay/stale binding, direct internal-service exposure.
- **Integration:** gateway ↔ downloads, ingest ↔ scanner ↔ store,
  browser-download event ↔ ingest, TinyAuth identity fixture.
- **E2E:** CloudBrowser download → durable store → TinyAuth → CloudFiles list →
  local attachment download.
- **Operational:** restart/recreate persistence, quota, 90-day purge, GDPR
  erasure, quarantine, backup/restore, health/readiness, and rollback.

The main acceptance test is not `/health`. It is the complete user journey for
owner A, plus an owner B isolation assertion, after a restart/recreate.

## 6. What to reuse and what not to reuse

### Reuse as evidence

- FR-12 durable per-user storage and agent access;
- old CloudFiles main-browser UX and attachment behavior;
- old TinyAuth group/domain intent;
- historical adversarial tests and incident cases;
- the new repository's `downloads/v1` owner-bound primitives where they meet
  this plan.

### Do not copy into the new product

- the old monolithic `downloads-api.py` HTTP/storage/template process;
- slot-local ownership or `Remote-Email` as the authority;
- direct public routing to the downloads container;
- implicit browser/HTML behavior in the router;
- credential, cookie, raw CDP, or unrestricted filesystem access;
- historical claims that were marked green without the new end-to-end evidence.

## 7. Suggested first implementation issue set

1. `spec(cloudfiles): approve public v1 contract and threat matrix`
2. `test(cloudfiles): add red gateway identity and route tests`
3. `feat(cloudfiles): implement pure owner/file domain`
4. `feat(cloudfiles): implement scan-before-publish ingest`
5. `feat(cloudfiles): implement internal downloads client`
6. `feat(cloudfiles): implement TinyAuth-backed public gateway`
7. `feat(cloudfiles): add lifecycle/quota/retention/erasure adapters`
8. `test(cloudfiles): run local end-to-end download journey`
9. `build(cloudfiles): add non-root image and provenance qualification`
10. `ops(cloudfiles): qualify deployment only after explicit approval`

Issues should land in dependency order. Each implementation issue must include
its contract references, focused red test, acceptance evidence, and rollback
impact.
