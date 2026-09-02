# Downloads API v1

The downloads service exposes the durable per-owner download area to
authenticated surfaces. The service is **not** a credential transport and
**does not** proxy browser, network, filesystem, or process control.

## Owner binding

The caller never declares a principal. The trusted router supplies the
authenticated server-derived identity via the `X-CB-Principal`, `X-CB-Profile`,
`X-CB-Browser`, and `X-CB-Generation` headers. The downloads service resolves
every request against the area rooted at `<store_root>/<principal_id>/`.

The service refuses to serve another principal's data. Cross-owner path
attempts and any name containing `/`, `\`, `..`, or starting with `.` are
rejected with `owner_mismatch` or `invalid_name` non-sensitive error codes.

## Authentication

Every request other than `GET /health` requires a shared secret presented via
the `X-CB-Trusted-Secret` header. The server compares the header against the
configured `CB_DOWNLOADS_SHARED_SECRET` using `hmac.compare_digest`. Missing or
mismatched secrets yield `401 unauthorized`. The header must carry at least 16
bytes.

## Endpoints

- `GET /health` — bounded service health metadata.
- `GET /api/files` — bounded list of `DownloadEntry` records for the requester.
- `GET /file/<name>` — bounded file bytes, **always** sent with
  `Content-Disposition: attachment`. The downloads service never renders
  inline; PDFs use `application/pdf`, everything else `application/octet-stream`.
- `GET /ready` — bounded readiness metadata.

## Response envelopes

```json
{
  "principal_id": "owner-a",
  "entries": [
    {"name": "invoice.pdf", "size": 1234, "mtime": 1735689600, "owner": "owner-a"}
  ]
}
```

The listing never carries file content, cookie values, credential material,
network bodies, or raw exception text. `DownloadEntry.owner` always equals
the server-derived principal.

## Mandatory denials

- Another principal's files, including any path containing `/`, `\`, or `..`.
- Hidden files (names starting with `.`) and the `.quarantine/` directory
  (surfaced in the listing only when explicitly permitted; never served).
- Secret-bearing names, embedded NUL bytes, or any path that escapes the
  owner area on `Path.resolve`.
- Mismatched or absent trusted secret.

## Implementation

- `cloudbrowser.downloads.store` — per-owner disk store.
- `cloudbrowser.downloads.service` — bounded contract surface.
- `cloudbrowser.downloads.api` — `ThreadingHTTPServer` shell.
- `cloudbrowser.downloads.identity` — `TrustedSecret`, header lookup, server
  identity.
- `cloudbrowser.downloads.contracts` — error types and value objects.

The release is installable after image publication and source-level runtime
and security acceptance pass. The v0.2.0-dev1 manifest records the immutable
CI-qualified images; deployed runtime qualification remains Step 19.
