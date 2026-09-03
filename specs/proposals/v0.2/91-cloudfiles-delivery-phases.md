# CloudFiles delivery phases

> Status: **planning map — 2026-09-03**

This is the short, chronological map for implementing the frozen CloudFiles
target. The detailed requirement is in
`specs/proposals/v0.2/89-cloudfiles-product-requirement.md`; the detailed
engineering plan is in `specs/proposals/v0.2/90-cloudfiles-development-plan.md`.

## Phase 0 — define and secure the boundary

**Purpose:** decide exactly what will be built before writing production code.

Work:

- approve the public `cloudfiles/v1` contract;
- keep `downloads/v1` as the internal data contract;
- define TinyAuth, gateway, identity-binding, ingest, scanner, retention, and
  deletion boundaries;
- write the route/response and threat matrices;
- write focused security tests and observe them fail.

Exit:

- public and internal contracts are versioned;
- security invariants are explicit;
- the red boundary tests exist and have actually failed;
- no public downloads implementation has been written yet.

**Current status:** target and plan documented; contract drafted; Phase 0
review, matrices, and red tests remain.

## Phase 1 — pure domain and storage policy

Implement without HTTP, TinyAuth, Chromium, or Coolify:

- owner identity and storage-key rules;
- safe filenames and duplicate-name allocation;
- storage confinement and metadata bounds;
- quota, retention, quarantine, and deletion decisions;
- unit and table-driven security tests.

Exit: domain tests are green and the owner/isolation rules are independently
verifiable.

## Phase 2 — ingest and internal integration

Implement:

- browser-download ingest port;
- bounded streams and temporary files;
- scan-before-publish and atomic publication;
- quarantine and idempotency;
- typed client for the existing internal `downloads/v1` service;
- fake browser event integration.

Exit: owner A can ingest and retrieve a clean file; infected, malformed,
cross-owner, and partial publication cases fail safely.

## Phase 3 — public CloudFiles gateway

Implement the separate `cloudfiles` service:

- TinyAuth-authenticated public identity boundary;
- `GET /` HTML listing;
- `GET /api/files` metadata;
- `GET /file/<name>` attachment retrieval;
- escaped templates, safe headers, no-store policy, bounded errors;
- internal-only communication with `downloads`.

Exit: local HTTP tests prove the authenticated main-browser listing and local
attachment download.

## Phase 4 — operational guarantees

Add and verify:

- 5 GB quota;
- 90-day retention janitor;
- GDPR erasure;
- ClamAV adapter and quarantine notification;
- durable-volume backup/restore;
- readiness, metrics, redacted audit, and EU-residency assertions.

Exit: lifecycle and failure-mode tests are green.

## Phase 5 — end-to-end and release qualification

Run the complete local journey:

```text
CloudBrowser download
  -> ingest
  -> durable owner area
  -> TinyAuth fixture
  -> CloudFiles listing
  -> local attachment download
```

Also prove multi-slot convergence, owner isolation, restart/recreate
persistence, quarantine, quota, retention, erasure, and rollback.

Then add the non-root CloudFiles image, CI qualification, provenance/SBOM,
digest pinning, and release-manifest entry.

Exit: source, security, E2E, image, and release gates all pass.

## Phase 6 — separately approved live rollout

Only after Phase 5 and a separate explicit approval:

1. deploy the new CloudFiles gateway;
2. route `cloudfiles2.dev01.pmo.city` to the gateway;
3. keep the downloads service internal;
4. apply the approved service-scoped TinyAuth configuration;
5. run authenticated persistence, isolation, binding, and rollback checks.

No step in Phases 0–5 authorizes deployment, DNS changes, credential rotation,
Traefik mutation, or live-fleet changes.

## Sequence at a glance

```text
Phase 0  Definition + threat model + red tests
   ↓
Phase 1  Pure domain + storage policy
   ↓
Phase 2  Ingest + internal downloads integration
   ↓
Phase 3  Public CloudFiles gateway
   ↓
Phase 4  Quota + retention + quarantine + erasure
   ↓
Phase 5  Local E2E + image/release qualification
   ↓
Phase 6  Explicitly approved live rollout
```
