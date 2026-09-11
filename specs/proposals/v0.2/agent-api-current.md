# Agent API — supported Hermes surface

> Current source contract, 2026-09-11. The versioned interfaces are the
> [Hermes MCP contract](../../contracts/hermes-mcp/v1/README.md),
> [control API](../../contracts/control-api/v1/README.md), and
> [agent-control API](../../contracts/agent-control/v1/contract.md).
> Source support is not deployment or live-user qualification.

## Supported entrypoint

Hermes launches `cloudbrowser-hermes-mcp` as a local stdio MCP server. The
bridge uses a profile-scoped authentication value, supplied to its subprocess
through Hermes secret scope, to call the TinyAuth-protected viewer origin.
TinyAuth and identity-link derive the immutable principal; the bridge cannot
submit `Remote-*`, principal, profile, slot, browser or generation authority.

The bridge rejects redirects, non-HTTPS remote origins, oversized/non-JSON
responses, unknown tools and extra arguments. It contains no CDP client and no
Vaultwarden integration. Authentication material never appears in tool input,
tool output or error content.

The former direct fleet-CDP Hermes helper is not supported. It exposed raw CDP
and unrestricted page evaluation, bypassed the owner-bound router, and was
removed from `integrations/hermes`.

## Implemented tools

| Tool | Request | Bounded result |
| --- | --- | --- |
| `cloudbrowser_start` | no arguments | current session state; activates an offered session |
| `cloudbrowser_tabs_list` | no arguments | public URL/title and exact opaque target IDs |
| `cloudbrowser_tab_open` | one HTTP(S) URL | the exact target created by Chromium |
| `cloudbrowser_navigate` | exact tab ID and HTTP(S) URL | status and exact target metadata |
| `cloudbrowser_click` | exact tab ID and bounded selector | status and exact target metadata |
| `cloudbrowser_type` | exact tab ID, bounded selector and ordinary non-secret text | status and exact target metadata |
| `cloudbrowser_page_info` | exact tab ID | bounded URL, title and text-first page state |
| `cloudbrowser_credential_login` | declared site ID and exact tab ID | status only |

Missing, unknown or stale tab IDs fail closed. `tab_open` is the supported
first-tab path for a fresh profile. The tool schemas use
`additionalProperties: false`; identity, credential reference, password and
binding fields cannot be smuggled through an MCP request.

## Credential login boundary

`cloudbrowser_credential_login` is an intent-only operation. The router derives
the current principal/profile/browser/generation, resolves the declared site,
and mints the broker's one-time exact-target capability. The broker alone
resolves authorized grant material and returns one of:

```json
{
  "status": "authenticated|mfa_required|failed|not_shared|unsupported",
  "error_code": null,
  "request_id": "opaque"
}
```

No credential, token, cookie, storage value, network body, password value,
grant reference or replayable credential handle is returned. Basic Auth and a
declared Authentik flow have synthetic real-Chromium coverage; production form
login, TOTP submission and direct human-code handoff remain outside M2.

An unknown login outcome is not automatically retried. Durable idempotency
records preserve that state across process restart so a duplicate request does
not cause another credential fill. Hermes should inspect the exact tab or ask
the employee before an explicit new attempt.

## Mandatory denials

The normal Hermes surface has no operation for:

- raw CDP or unrestricted evaluation;
- cookies, storage values, network bodies or authorization headers;
- credential material, password values, OTP seeds/codes or grant files;
- filesystem, process, host/container metadata or another owner's browser;
- caller-selected principal, profile, slot, browser or generation.

## Authentication qualification boundary

For the controlled pilot, the operator provisions one distinct
TinyAuth-compatible authorization value per Hermes profile, or a time-bounded
session cookie, in Hermes secret scope. The bridge refuses zero or multiple
authentication channels. Interactive OIDC acquisition and renewal are not
implemented by this source increment; they need a separate integration decision
before multi-user acceptance. A shared deployment-wide identity is prohibited.

## Later surface work

Back/forward/reload, scroll/key input, richer accessibility observation,
screenshots, tab activation/close and downloads are product candidates, not
deployed tools. Each needs an explicit bounded contract and secret-observation
review before addition. The M3 viewer/takeover work must also arbitrate human
and agent input; the MCP bridge does not imply that this is already solved.
