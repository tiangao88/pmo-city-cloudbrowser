# Hermes MCP v1

This is CloudBrowser's supported Hermes entrypoint. The
`cloudbrowser-hermes-mcp` executable is a local stdio MCP server. Hermes injects
one profile-scoped edge-authentication value into that subprocess and the
bridge calls the authenticated CloudBrowser viewer origin over HTTPS.

The authentication value is control-plane authorization, not an application
credential or Vaultwarden grant. It is never a tool argument, result, log or
error. The bridge refuses redirects so it cannot forward the value to an IdP
or a different origin. It never sends `Remote-*`, owner, profile, slot, browser
or generation headers; TinyAuth and identity-link derive those server-side.

## Configuration

Required:

- `CB_CLOUDBROWSER_URL`: an HTTPS origin without userinfo, path, query or
  fragment. Plain HTTP is accepted only for loopback tests.
- exactly one of `CB_CLOUDBROWSER_AUTHORIZATION` or
  `CB_CLOUDBROWSER_COOKIE`, injected through the Hermes profile secret scope.

Optional:

- `CB_CLOUDBROWSER_TIMEOUT_S`: positive request deadline no greater than 30
  seconds; default 15.

The bridge exposes eight tools: `cloudbrowser_start`,
`cloudbrowser_tabs_list`, `cloudbrowser_tab_open`, `cloudbrowser_navigate`,
`cloudbrowser_click`, `cloudbrowser_type`, `cloudbrowser_page_info`, and
`cloudbrowser_credential_login`. Their input schemas reject extra fields.
Page actions use exact Chromium target IDs. Login accepts only a declared
`site_id` and exact `target_tab_id` and returns bounded status without
credential material.

Page text is limited to 4096 UTF-8 bytes. Longer pages return an excerpt ending
with `[Page text truncated to 4096 UTF-8 bytes]`; the agent must not claim to
have read content beyond that excerpt. Oversized URLs/titles and malformed
responses remain errors.

The stdio transport uses newline-delimited UTF-8 JSON-RPC and caps each input
message at 64 KiB. It supports `initialize`, `ping`, `tools/list`,
`tools/call`, and notifications. Unknown methods and tools fail closed.

## Authentication boundary

The operator must provision a distinct per-profile TinyAuth-compatible
authorization value or controlled session cookie. A shared deployment-wide
credential is not supported. Copying an interactive cookie is acceptable only
for a time-bounded controlled test; an expired/revoked value returns
`unauthorized` and requires reauthorization. Automated OIDC token acquisition
is not implemented by this bridge and is not implied by this source milestone.

## Outcome and retry rules

Transport, redirect and non-JSON failures return a bounded error. A login call
whose outcome is unknown must not be repeated automatically because the first
request may have reached the broker. Hermes should inspect the exact tab or ask
the employee before an explicit retry.
