# Downloads service

The downloads service exposes the durable per-owner download area to the
authenticated viewer and agent surfaces. Identity is **server-derived** from
the trusted router (no `Remote-Email` header trust); every request resolves
against `<CB_DOWNLOADS_ROOT>/<principal_id>/`.

## Surface

This service is the internal `downloads/v1` data boundary. The public
CloudFiles gateway (specified in
`specs/proposals/v0.2/89-cloudfiles-product-requirement.md`) owns the
TinyAuth-protected HTML surface in the employee's normal browser; it is not
implemented by this service.

- `GET /health` — bounded non-sensitive health metadata.
- `GET /api/files` — bounded list of `{name, size, mtime, owner}` entries.
- `GET /file/<name>` — bounded file bytes, **always** `Content-Disposition:
  attachment`. The downloads service never renders inline.
- `GET /ready` — bounded readiness metadata.

This service implements the internal `downloads/v1` boundary. The separate
CloudFiles service now implements the public gateway, HTML and ingest receiver;
the browser service supplies completed-download events. The frozen target is in
`specs/proposals/v0.2/89-cloudfiles-product-requirement.md` and
current evidence is in `specs/proposals/v0.2/IMPLEMENTATION-STATUS.md`.

The public product target is deliberately separate from this service:
`cloudfiles2.dev01.pmo.city` must terminate at a TinyAuth-protected CloudFiles
gateway, which forwards a server-derived owner binding to this internal
service. Do not expose this container directly as the public CloudFiles host.

## Authentication
present `CB_DOWNLOADS_SHARED_SECRET` via the `X-CB-Trusted-Secret` header. The
service compares the header against the configured secret with
`hmac.compare_digest`; missing or mismatched secrets yield `401 unauthorized`.

## Required environment

- `CB_INSTANCE_ID` — instance namespace; never falls back.
- `CB_RELEASE_VERSION` — release marker; never falls back.
- `CB_PORT` — bound HTTP port (default 8083).
- `CB_PRINCIPAL_ID`, `CB_BROWSER_ID`, `CB_BINDING_GENERATION` — owner binding.
- `CB_DOWNLOADS_SHARED_SECRET` — trusted-router shared secret (≥ 16 bytes).
- `CB_DOWNLOADS_ROOT` — durable area root (default `/data/downloads`).

## Implementation

- `src/cloudbrowser/downloads/contracts.py` — value objects, error types.
- `src/cloudbrowser/downloads/store.py` — per-owner disk store with path
  safety and `.quarantine/` exclusion.
- `src/cloudbrowser/downloads/service.py` — bounded contract surface.
- `src/cloudbrowser/downloads/identity.py` — `TrustedSecret`, server identity.
- `src/cloudbrowser/downloads/api.py` — `ThreadingHTTPServer` shell.

The current v0.2.0-dev1 manifest is pre-build and not installable. Retained
digests qualify prior source only. Build, image/runtime qualification and
integrated user-journey acceptance must be recorded for the candidate release.
