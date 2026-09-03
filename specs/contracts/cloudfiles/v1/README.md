# CloudFiles public gateway contract v1

> Version: **v0.2 development proposal — 2026-09-03**
> Status: **PROPOSED — implementation follows the CloudFiles product target**

This is the public application contract for CloudFiles. It is distinct from
`downloads/v1`, which is the internal owner-bound data contract.

## Boundary

The public host is `cloudfiles2.dev01.pmo.city`. Requests enter through
TinyAuth and the PMO City `PMOC_Users` policy, then terminate at the CloudFiles
gateway. The gateway resolves the authenticated subject to a server-derived
principal binding and calls the internal downloads service. The downloads
service is never the public product target.

The gateway must not treat client-supplied `Remote-Email`, owner, principal,
profile, browser, generation, or path headers as authoritative. Missing,
ambiguous, revoked, or stale identity bindings fail closed.

## Routes

| Method | Path | Authentication | Result |
|---|---|---|---|
| `GET` | `/health` | none | bounded health metadata |
| `GET` | `/ready` | gateway/dependency check | bounded readiness metadata |
| `GET` | `/` | TinyAuth + server binding | escaped CloudFiles HTML listing |
| `GET` | `/api/files` | TinyAuth + server binding | bounded JSON metadata listing |
| `GET` | `/file/<name>` | TinyAuth + server binding | attachment bytes |

The public gateway does not expose arbitrary proxying, raw storage paths,
internal secrets, browser/CDP control, or inline file rendering.

## Listing response

The JSON response is bounded and contains only safe metadata:

```json
{
  "entries": [
    {"name": "invoice.pdf", "size": 1234, "mtime": 1735689600}
  ]
}
```

The public response must not include the principal identifier, credential
material, cookies, tokens, network bodies, absolute storage paths, quarantine
names, or internal shared-secret details.

## File response

A successful file response:

- uses `Content-Disposition: attachment` with a validated filename;
- uses an allowlisted content type, defaulting to
  `application/octet-stream`;
- is bounded by the configured maximum file size;
- sends owner data with `Cache-Control: no-store`;
- never renders content inline in the CloudFiles page.

## Identity and errors

TinyAuth is the public authentication gate. It is not the internal service
authorization mechanism. The gateway supplies a fresh request ID and a
server-derived binding to `downloads/v1` over the trusted internal client.

Responses use bounded non-sensitive error codes such as:

- `unauthorized` — no valid TinyAuth/trusted binding;
- `owner_binding_unavailable` — the subject cannot be resolved safely;
- `invalid_name` — the file name is not a valid flat name;
- `not_found` — the owner has no such retrievable file;
- `dependency_unavailable` — the internal service cannot be reached.

No response or log may echo secrets, arbitrary request headers, filesystem
paths, or file contents.

## Acceptance

A v1 implementation is contract-complete only when it proves the complete
employee journey: a file is ingested from an owner-bound CloudBrowser, appears
in the authenticated main-browser listing, and downloads locally as an
attachment. It must also prove owner isolation and persistence across a
browser/service restart. `/health` alone is not acceptance.
