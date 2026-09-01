# Agent API — MCP Surface for Hermes (draft)

> **Refactor update — 2026-09-01:** `credential.login` is now specified as a
> broker intent, not merely a comment. Its request is profile/principal/site
> bound by the server and its response is status-only. The normal agent/CDP
> surface must not expose grant material, cookies, storage, network bodies,
> password values, or unrestricted runtime evaluation. See
> `85-credential-broker-prd.md`, `86-product-boundaries.md`, and
> `87-broker-security-model.md`. This remains a proposed contract until the
> refactor is agreed and implemented.

## Principles

- The agent drives **its owner's single browser** (FR-2/FR-11) — no
  cross-user access (FR-8).
- The agent sees **page state only** — credentials never enter the LLM
  context (FR-7/FR-9).
- The surface is served over **MCP** (Streamable HTTP), behind Tinyauth SSO
  (FR-3), per-user token.

## Tool groups (full control — D1)

| Group | Tools | Notes |
|---|---|---|
| **Navigation** | `navigate(url)`, `back()`, `forward()`, `reload()` | Chromium engine (C1) |
| **Interaction** | `click(selector)`, `type(selector, text)`, `scroll(direction, amount)`, `press_key(key)` | selectors = CSS/XPath; text-first page state (browser-use harness) |
| **Extraction** | `extract(selector?)`, `page_info()`, `get_url()`, `get_title()` | text-first, no raw HTML dumps (FR-4 research note) |
| **Screenshot** | `screenshot()` | on demand, not by default |
| **Tabs** | `tabs.list()`, `tabs.open(url)`, `tabs.activate(id)`, `tabs.close(id)` | tabs = the separation mechanism (gate Q1) |
| **Downloads** | `downloads.list()`, `downloads.get(path)` | durable per-user area (FR-12, I1/I2/I5); agent can read/process/summarize/re-send (I4) |
| **Browser identity** | `browser.list()`, `browser.attach(browser_id)` | single browser per user (FR-11); attach is a formality, kept for API stability |

## Intents that are NOT agent tools (deterministic broker boundary)

`credential.login(site, username)` is an **intent-only broker operation**.
The agent may request it, but it does not receive credentials, tokens, cookie
values, DOM values, network bodies, or a replayable handle.

### Proposed request contract

```json
{
  "site_id": "declared-site",
  "username_ref": "declared-account",
  "target_tab_id": "optional-owner-tab",
  "idempotency_key": "optional"
}
```

`profile_id`, immutable `principal_id`, browser/slot ownership, deployment,
site declaration, adapter version, request nonce, and expiry are derived or
bound server-side. Caller-supplied identity, slot, browser, and origin are
never authoritative.

### Proposed response contract

```json
{
  "status": "authenticated|mfa_required|failed|not_shared|unsupported",
  "error_code": null,
  "request_id": "opaque",
  "duration_ms": 0
}
```

The response is status-only. Safe error codes are bounded and must not contain
raw exception text, URLs with credentials, page text, selectors, or secret
values. See `85-credential-broker-prd.md` and
`87-broker-security-model.md`.

### Credential and MFA rules

- The deterministic broker fetches and fills credentials; the agent never
  imports a vault client or reads grant material.
- Authentik/TinyAuth is one explicit SSO adapter, not the generic broker.
- Form login, HTTP Basic, SSO, TOTP, and one-time human-code handoff are
  adapter classes behind the same intent contract.
- Stored TOTP is broker-only. Without a seed, the agent asks the employee for
  a one-time code, which is submitted to the broker and never returned to the
  agent. Unsupported MFA fails closed.

## Browser-control security boundary

The full-control list below is a product goal, not permission for unrestricted
raw CDP. The normal agent surface must deny or mediate cookie/value reads,
browser storage, network bodies/authorization headers, password input values,
unrestricted `Runtime.evaluate`, raw CDP sockets, filesystem/process access,
grant paths, and undeclared credential origins. The broker receives a separate
request-scoped fill/verification capability. See
`86-product-boundaries.md` and `87-broker-security-model.md`.

## Open details (POC)

- Exact selector syntax and accessibility-tree usage (browser-use harness
  conventions).
- Whether `downloads.get` streams or returns a link (SSO-gated link under
  the viewer domain is the default).
- Concurrency: one agent drive at a time vs multiplexed viewer+agent on the
  same CDP target (H6 — POC detail).
