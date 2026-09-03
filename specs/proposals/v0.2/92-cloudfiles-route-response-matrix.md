# CloudFiles route and response matrix (Phase 0)

> Version: **v0.2 development proposal — 2026-09-03**
> Status: **PROPOSED — Phase 0 boundary document**

This matrix defines the public CloudFiles surface and the response envelope for
each route. It is derived from
`specs/proposals/v0.2/89-cloudfiles-product-requirement.md` and
`specs/contracts/cloudfiles/v1/README.md`.

## Host and trust

- Public host: `cloudfiles2.dev01.pmo.city`
- Edge authentication: TinyAuth + PMO City `PMOC_Users`
- Server-derived binding: required for any authenticated route
- Identity source of truth: TinyAuth subject mapped by the gateway to the
  immutable PMO principal
- Forbidden authority: `Remote-Email`, `X-CB-Principal`,
  `X-CB-Profile`, `X-CB-Browser`, `X-CB-Generation`, `X-CB-Owner`, query-string
  owner/path parameters, or any client-supplied identity header
- Rejection: missing, ambiguous, revoked, or stale binding → fail closed

## Public CloudFiles gateway routes

| Method | Path | Authentication | Outcome |
|---|---|---|---|
| `GET` | `/health` | none | `200` bounded `{"status":"ok","component":"cloudfiles"}` or `503` if dependency missing |
| `GET` | `/ready` | none | `200` if identity resolver, internal `downloads/v1`, and storage backend are reachable; `503` otherwise |
| `GET` | `/` | TinyAuth + binding | `200` escaped HTML listing; `401` if no TinyAuth; `503` if binding missing |
| `GET` | `/api/files` | TinyAuth + binding | `200` bounded JSON listing; `401`/`503` per above |
| `GET` | `/file/<name>` | TinyAuth + binding | `200` attachment bytes; `400 invalid_name`, `404 not_found`, `401`/`503` per above |
| any | `/*` other | n/a | `404 not_found` (gateway must not proxy) |

## Internal `downloads/v1` routes (gateway-facing)

These are NOT public. Only the gateway may call them over the internal network
with a server-held shared secret.

| Method | Path | Source | Outcome |
|---|---|---|---|
| `GET` | `/health` | gateway | `200` bounded health; `401` if secret missing on non-`/health` |
| `GET` | `/ready` | gateway | `200` ready; `503` if storage/scanner unreachable |
| `GET` | `/api/files` | gateway | `200` bounded metadata; `401` on bad secret; `400` on bad binding; `503` on dependency |
| `GET` | `/file/<name>` | gateway | `200` attachment; `401`/`400`/`404` per above; `403 owner_mismatch` if binding tries to cross principals |
| any | `/*` other | n/a | `404 not_found` (no new public surface) |

## Response envelope contract

Public gateway responses are always:

- `Content-Type: application/json; charset=utf-8` for `/health`, `/ready`,
  `/api/files`, and error responses;
- `Content-Type: text/html; charset=utf-8` for `/` with `Content-Security-Policy`
  `default-src 'none'; style-src 'unsafe-inline'; img-src data:`,
  `Referrer-Policy: no-referrer`, `Cache-Control: no-store`;
- `Content-Disposition: attachment; filename="<safe-name>"` for `/file/<name>`,
  with allowlisted content type;
- `Cache-Control: no-store` for `/api/files` and `/file/<name>`;
- `Server: cloudfiles` (no version); no `X-Powered-By`.

Public response bodies never include:

- the raw principal identifier, password, token, OTP seed, cookie, network
  body, raw storage path, quarantine name, or internal shared secret;
- request body contents, internal headers, or dependency URLs.

Public error envelope (uniform for all routes):

```json
{
  "error_code": "invalid_name",
  "request_id": "req-..."
}
```

Allowed error codes:

- `unauthorized`
- `owner_binding_unavailable`
- `forbidden_owner_mismatch`
- `invalid_name`
- `not_found`
- `dependency_unavailable`
- `too_large`
- `unsupported_media_type`
- `rate_limited`
- `internal_error`

The gateway must not echo raw request headers, paths, or bodies.

## Cross-principal invariant

For any pair of distinct principals A and B:

- `/api/files` for A must never include B's files;
- `/file/<name>` for A with B's binding must never return B's bytes;
- storage paths under the downloads service must never be reachable across
  principal boundaries;
- no header combination (`Remote-Email`, `X-CB-*`, query string, body) may
  override the server-derived binding.

## Public-host restrictions

- The downloads container must not be the public host target.
- `cloudfiles2.dev01.pmo.city` must terminate at the gateway container.
- Traefik routers for the public host are configured in the deployment layer,
  not in compose-authored router rules (avoid duplicate router conflicts).
- TinyAuth application keys for the gateway are stable, short, and explicit
  (for example `cloudfiles2`); they are not raw container UUIDs.

## Status

Phase 0 entry: this matrix is the source of truth for the red tests in
`specs/proposals/v0.2/93-cloudfiles-phase0-red-tests.md` and for the Phase 1
implementation contracts.
