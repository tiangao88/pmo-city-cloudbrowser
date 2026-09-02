# Downloads API v1 (contracts index)

The downloads service exposes the durable per-owner download area to
authenticated surfaces. The service is **not** a credential transport and
**does not** proxy browser, network, filesystem, or process control.

- Public host: `cloudfiles2.dev01.pmo.city` (env `CB_PUBLIC_FILES_HOST`).
- Owner binding: server-derived from `X-CB-Principal` headers; no
  caller-declared principal is honored. The on-disk layout uses
  `sha256(principal_id)` so the principal is never encoded in any path.
- Authentication: trusted router shared secret in `X-CB-Trusted-Secret`
  (`CB_DOWNLOADS_SHARED_SECRET`, ≥16 bytes), constant-time comparison.
- Endpoints: `GET /health`, `GET /api/files`, `GET /file/<name>` (attachment
  only), `GET /ready`.
- Mandatory denials: cross-owner paths, hidden names, encoded traversal,
  control characters, symlinked storage, oversized payloads.

See `contract.md` in this directory for the full request/response envelope,
denials, and implementation reference.

## Release status

The v0.2 release manifest remains `installable: false` until image
publication, runtime, and security acceptance pass.
