# Durable downloads requirements

> Version: **v0.2 development proposal — 2026-09-02**  
> Status: **implemented in the step-16 contract slice; runtime acceptance pending**

## Goal

Expose a persistent, per-principal Cloud Files surface at
`cloudfiles2.dev01.pmo.city` without sharing data between users or exposing
slot-local browser storage.

## Requirements

- File bytes are stored under the instance-scoped `downloads` volume and a
  deterministic non-PII owner key derived from the server-bound principal.
- The public service never trusts `Remote-Email` as its authoritative identity;
  trusted ingress supplies the server-derived principal binding.
- Ingest and retrieval are bounded and attachment-only. No inline rendering,
  path traversal, symlink following, hidden-file access, CR/LF filename header
  injection, or cross-owner access is permitted.
- `/health` is unauthenticated and bounded. File routes require the trusted
  router shared secret and server-derived identity.
- Quarantine entries may be retained for operator inspection but are never
  retrievable through the file route.
- The service remains independently deployable, non-root, and limited to its
  own `/data/downloads` volume. It does not import or mount the legacy runtime.

## Explicit non-goals for this slice

- Live Coolify creation, deployment, DNS changes, or Traefik/tinyauth mutation.
- Browser download capture via CDP. The broker/agent control plane will use
  the service ingest seam; browser-side capture is a later integration.
- ClamAV execution, retention janitor, and quota enforcement. These remain
  installability/runtime acceptance gates and must be connected before a
  production release.
