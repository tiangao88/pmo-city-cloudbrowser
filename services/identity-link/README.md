# Internal PMO identity-link service

This service owns the durable identity-link SQLite database. CloudFiles and
Viewer query it over the private compose network; they never mount or write
its database directly.

## Environment

- `CB_IDENTITY_LINK_SHARED_SECRET` (required) — internal client secret.
- `CB_OIDC_ISSUER` (required) — namespace for OIDC `Remote-Sub` keys.
- `CB_TINYAUTH_REALM` (required) — namespace for local TinyAuth `Remote-User` keys.
- `CB_IDENTITY_LINK_DB` (default `/data/identity-links.sqlite3`) — durable DB path.
- `CB_PORT` (default `8091`) — private listen port.

The service generates opaque PMO IDs server-side, provisions only after the
request carries `PMOC_Users`, ignores email, and retains revocations as
 tombstones.
