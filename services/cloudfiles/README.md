# CloudFiles public gateway service

The gateway owns the public listing and attachment routes. TinyAuth is an edge
concern; only a validated, server-provided session enters the gateway identity
boundary. Internal downloads traffic remains owner-bound and private.

## Environment

- `CB_DOWNLOADS_BASE_URL` (required) — internal downloads service base URL.
- `CB_DOWNLOADS_SHARED_SECRET` (required) — server-held secret for the
  internal trusted-secret boundary.
- `CB_IDENTITY_LINK_BASE_URL` (required when `CB_EDGE_AUTH` is enabled) —
  internal PMO identity-link service URL.
- `CB_IDENTITY_LINK_SHARED_SECRET` (required when `CB_EDGE_AUTH` is enabled) —
  service-to-service authentication secret.
- `CB_OIDC_ISSUER` / `CB_TINYAUTH_REALM` (required when edge auth is enabled) —
  namespaces for OIDC `Remote-Sub` and local TinyAuth `Remote-User` keys.
- `CB_INSTANCE_ID` / `CB_RELEASE_VERSION` (required) — instance and release
  identity for bounded health metadata.
- `CB_PORT` (default `8085`) — listen port.
- `CB_EDGE_AUTH` — unset (default): the gateway serves fail-closed; every
  protected route returns `unauthorized` because no TinyAuth session can
  exist. `traefik-forwardauth`: the entrypoint wraps the gateway with the
  shared identity-link resolver. It requires the `PMOC_Users` group, uses
  `Remote-Sub` first and `Remote-User` for local TinyAuth accounts, and never
  uses `Remote-Email` as authority. Any other value refuses to start.
