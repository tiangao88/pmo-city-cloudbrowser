# Viewer service

The viewer owns the authenticated user-facing browser surface. This slice
provides an owner-bound, expiring session registry and a deliberately bounded
HTTP shell on port `8082`.

## Boundary

- The router or authenticated control plane must derive the
  `profile_id`, `principal_id`, `browser_id`, and `generation` fields.
- `CB_VIEWER_TOKEN_SECRET` is required at service startup and must be supplied
  by the deployment secret store; it is never returned by the API.
- `CB_VIEWER_SESSION_TTL_S` defaults to 360 seconds and is capped by the
  session implementation at one hour.
- `GET /viewer` requires an authenticated viewer session and
  returns a no-store HTML shell.
- `POST /viewer/session` revalidates the complete owner binding and returns
  only non-sensitive session metadata.
- `/raw-cdp`, profile paths, credential paths, and arbitrary proxy routes do
  not exist.

The `ViewerBrowserBridge` provides the next internal seam for connecting the
session to a separately mediated browser stream. It accepts only an internal
relative endpoint and requires a matching owner/generation readiness result.
It does not expose a CDP socket or browser credentials.

This is a source-built development slice. It does not claim a production
viewer integration, external IdP validation, WebRTC/noVNC/neko deployment, or
installable release status. Those remain acceptance gates.
