---
name: cloudbrowser
description: "Use an employee's owner-bound PMO City CloudBrowser through mediated MCP tools."
version: 2.0.0
author: PMO City
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [cloudbrowser, browser, pmo-city, mcp]
---

# CloudBrowser

Use these tools when a task should run in the employee's persistent PMO City
browser. They act only on the browser resolved from the authenticated Hermes
profile. Never use a direct CDP URL, `browser_exec`, shell HTTP calls or page
JavaScript as a substitute.

## Normal sequence

1. Call `cloudbrowser_start`. If it returns `waiting`, report that the browser
   is queued and retry only after the user asks or a later task step. If it
   returns `active`, continue.
2. Call `cloudbrowser_tabs_list`. Reuse the intended tab only when its returned
   public URL/title make the target unambiguous.
3. For a fresh browser or a new task, call `cloudbrowser_tab_open` and retain
   the exact returned `tab_id`.
4. Pass that exact `target_tab_id` to navigate, click, type and page-info calls.
   A missing or stale ID is a real failure; do not guess another tab.
5. Use `cloudbrowser_page_info` for bounded text-first observation between
   actions.
6. When a declared site needs credentials, call
   `cloudbrowser_credential_login(site_id, target_tab_id)`. Never type a
   password, access token, session cookie or one-time code with
   `cloudbrowser_type`.

## Available tools

- `cloudbrowser_start()`
- `cloudbrowser_tabs_list()`
- `cloudbrowser_tab_open(url)`
- `cloudbrowser_navigate(target_tab_id, url)`
- `cloudbrowser_click(target_tab_id, selector)`
- `cloudbrowser_type(target_tab_id, selector, text)` for ordinary non-secret text
- `cloudbrowser_page_info(target_tab_id)`
- `cloudbrowser_credential_login(site_id, target_tab_id)`

The login tool returns status only: `authenticated`, `mfa_required`, `failed`,
`not_shared` or `unsupported`. For `mfa_required` or `unsupported`, explain the
handoff instead of improvising a login. For an unknown/transport outcome, do
not automatically repeat the login; ask the user to inspect the current page
or retry explicitly.

## Prohibited workarounds

Do not request or reveal credentials, cookies, storage, authorization headers,
network bodies, raw HTML, raw CDP, unrestricted evaluation, host files or
process access. Do not put identity, owner, profile, slot, browser or generation
fields into tool arguments. Those bindings are server-derived.
