# Downloads service

The downloads service exposes the durable per-owner download area to the
authenticated viewer and agent surfaces. Identity is **server-derived** from
the trusted router (no `Remote-Email` header trust); every request resolves
against `<CB_DOWNLOADS_ROOT>/<principal_id>/`.

## Surface

- `GET /health` — bounded non-sensitive health metadata.
- `GET /api/files` — bounded list of `{name, size, mtime, owner}` entries.
- `GET /file/<name>` — bounded file bytes, **always** `Content-Disposition:
  attachment`. The downloads service never renders inline.
- `GET /ready` — bounded readiness metadata.

## Authentication

Every request other than `/health` and `/ready` requires the trusted router to
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

The release is installable after image publication and source-level runtime,
security, and release qualification pass. The v0.2.0-dev1 manifest records the
immutable CI-qualified images; deployed runtime qualification remains Step 19.
