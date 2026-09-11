# Viewer service

The viewer owns the authenticated user-facing control surface on port `8082`.
It implements queue join/status/activation, roster, leave/release and a router
relay for exact-target page actions. The HTML shell is interactive; a live
browser video stream and user/agent takeover protocol remain roadmap work.

The approved next increment is [M3a viewer foundation](../../docs/M3-VIEWER-FOUNDATION.md):
prove same-Chromium rendering, then owner-bound live view and exclusive human
input before M2b application-login acceptance. Neko is a candidate, not an
installed transport. Current Chromium is headless; embedding a separate Neko
room would not satisfy the shared-browser requirement.

## Boundary

- The router or authenticated control plane must derive the
  `profile_id`, `principal_id`, `browser_id`, and `generation` fields.
- `CB_VIEWER_TOKEN_SECRET` is required at service startup and must be supplied
  by the deployment secret store; it is never returned by the API.
- `CB_VIEWER_SESSION_TTL_S` defaults to 360 seconds and is capped by the
  session implementation at one hour.
- When `CB_EDGE_AUTH=traefik-forwardauth`, the viewer uses the same internal
  PMO identity-link service as CloudFiles. OIDC `Remote-Sub` is primary;
  local TinyAuth accounts use namespaced `Remote-User`; `Remote-Email` is never
  an authority. `CB_IDENTITY_LINK_BASE_URL`,
  `CB_IDENTITY_LINK_SHARED_SECRET`, `CB_OIDC_ISSUER`, and
  `CB_TINYAUTH_REALM` are required in this mode. If edge auth is unset, the
  viewer remains bearer-token-only.
- `GET /` and `GET /viewer` return a no-store HTML shell to an authorized
  employee (resolved edge identity or valid bearer viewer session) and never
  echo identity values; `POST /viewer/session` revalidates the complete owner
  binding and returns only non-sensitive session metadata.
- `/raw-cdp`, profile paths, credential paths, and arbitrary proxy routes do
  not exist.

The `ViewerBrowserBridge` provides the next internal seam for connecting the
session to a separately mediated browser stream. It accepts only an internal
relative endpoint and requires a matching owner/generation readiness result.
It does not expose a CDP socket or browser credentials.

The supported Hermes stdio MCP bridge calls the same `/ui/session/*`,
`/ui/agent/*`, and `/ui/credential/login` routes through the authenticated
public viewer origin. The bridge sends only its profile-scoped edge
authentication and request data; this service continues to derive identity
through TinyAuth and identity-link and drops cookies/authorization before
relaying to the router. See the
[Hermes MCP contract](../../specs/contracts/hermes-mcp/v1/README.md).

This source does not establish a live streaming viewer or current release
qualification. See [status](../../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md)
and the proposed [roadmap](../../specs/proposals/v0.2/ROADMAP.md).
