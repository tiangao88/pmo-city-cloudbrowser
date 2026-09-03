# CloudFiles product requirement

> Version: **v0.2 development proposal — 2026-09-03**
> Status: **FROZEN TARGET — agreed by Tigo 2026-09-03**
> This requirement freezes the product outcome. It does not authorize live
> deployment, DNS changes, credential rotation, or fleet mutation.

## 1. Product decision

**CloudFiles is the authenticated, user-scoped file door in the employee's
normal/main browser.** A file downloaded inside CloudBrowser must be placed in
the employee's durable CloudFiles area and must later be downloadable to the
employee's local computer from `cloudfiles2.dev01.pmo.city`.

CloudFiles is not a slot-local downloads page, a browser-internal-only API, or
a second way to expose raw browser storage. The public product flow is:

```text
CloudBrowser download
        -> durable per-principal CloudFiles area
        -> TinyAuth-protected CloudFiles web surface
        -> file list in the employee's main browser
        -> attachment download to the employee's computer
```

This document freezes the target behavior. The implementation may be entirely
new; the legacy `downloads-api.py`, router, and TinyAuth wiring are references
for requirements and compatibility evidence, not code to copy.

## 2. User journeys

### 2.1 Employee download and find-back

1. An employee downloads a file in their owner-bound CloudBrowser.
2. CloudBrowser automatically writes the file to the durable CloudFiles area;
   there is no per-download destination choice.
3. The employee opens CloudFiles in the normal/parent browser.
4. TinyAuth authenticates the employee and authorizes the PMOC_Users group.
5. CloudFiles lists that employee's available files and safe metadata.
6. Selecting a file returns it as an attachment, so the normal browser saves it
   locally.
7. The same area remains available after browser restart, slot recreation, and
   service restart.

### 2.2 Agent access

The owner's Hermes agent may use the separately governed downloads contract to
list, read, process, summarize, and resend the owner's files. Agent access is
not a bypass around CloudFiles authorization and never grants cross-owner
access or credential/browser-control capabilities.

### 2.3 Isolation

Two principals must never see or retrieve each other's files. The owner key is
derived server-side from the immutable principal/user identifier; no public
request may select an owner by supplying an arbitrary email or path.

Files from multiple browser slots belonging to the same principal resolve to
the same durable owner area. Sharing across independent CloudBrowser
installations is **not** implied by this requirement and needs a separate
storage/identity design.

## 3. Security and edge requirements

- CloudFiles is protected at the public edge by TinyAuth, using the existing
  PMO City SSO policy and `PMOC_Users` authorization. `/health` may remain
  unauthenticated for bounded operations health checks.
- The public gateway, not the browser and not the client, derives the principal
  binding from the authenticated request.
- The downloads service is internal. It authenticates gateway requests with a
  server-held shared secret and validates server-derived principal, profile,
  browser, generation, and request identifiers.
- Client-supplied `Remote-Email`, owner, principal, path, or similar headers are
  never authoritative.
- Retrieval is attachment-only. No inline rendering, path traversal, hidden
  names, symlink escape, CR/LF filename injection, oversized payload, or
  cross-owner path is permitted.
- Secrets, cookies, tokens, credential material, network bodies, and raw CDP
  data never enter the CloudFiles UI, download metadata, logs, or the agent's
  model context.
- Security failures use bounded non-sensitive error codes and request IDs.

## 4. Functional requirements

The first installable CloudFiles slice must provide:

- `GET /health` — bounded health metadata;
- `GET /ready` — readiness for the public gateway/downloads dependency;
- `GET /` — authenticated CloudFiles HTML surface;
- `GET /api/files` — authenticated bounded metadata listing;
- `GET /file/<name>` — authenticated attachment retrieval;
- a browser-download ingest seam that writes to the owner's durable area;
- duplicate-name allocation (`file.pdf`, `file (1).pdf`, …);
- a stable, instance-scoped durable volume with one area per principal.

The service must implement the existing `downloads/v1` contract for internal
listing and retrieval. The HTML gateway is an additional public product
surface; it must not weaken or replace the internal trusted-secret boundary.

## 5. Storage and lifecycle acceptance

Before this requirement is marked implemented, tests and runtime evidence must
show:

- 5 GB per-principal quota enforcement;
- 90-day retention purge;
- GDPR erasure on principal deletion;
- ClamAV scan at ingest, with flagged files quarantined and not retrievable;
- persistence across browser restart, slot recreation, and service stop/start;
- same-principal multi-slot convergence;
- cross-principal isolation;
- EU-resident backing storage for client data.

A release cannot be called CloudFiles-complete if it only proves `/health` or
an internal API response.

## 6. Explicit non-goals of this frozen target

- Copying or importing the legacy `downloads-api.py` implementation.
- Exposing the downloads container directly as the public product boundary.
- Trusting TinyAuth headers without a server-owned gateway/binding step.
- Making CloudFiles open inside the embedded kiosk as the primary user flow.
- Sharing data between independent installations without an explicit storage
  contract.
- Live Coolify, DNS, Traefik, or TinyAuth changes as part of this document.

## 7. Traceability

The requirement consolidates the accepted intent from the archived sources:

- `archive/pmo-city-builds-w2-w3/02-functional-requirements.md` — FR-12,
  durable per-user storage and agent access;
- `archive/pmo-city-builds-w2-w3/23-d15-sso.md` — CloudFiles as the public
  SSO'd door;
- `archive/pmo-city-builds-w2-w3/48-kiosk-open-ux.md` — main-browser download
  destination;
- `archive/pmo-city-builds-w2-w3/07-agent-api.md` — agent downloads surface;
- `proposals/v0.2/88-downloads-contract.md` and `contracts/downloads/v1/` —
  new owner-bound internal contract.

The archived artifacts remain historical evidence. This document is the
current product target for the new repository.
