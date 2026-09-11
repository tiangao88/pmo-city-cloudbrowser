# CloudBrowser Agent Control API v1

Intent-only and restricted browser-control surface. The implementation must
not expose credential material, cookie/storage values, network bodies/auth
headers, unrestricted CDP, filesystem, or process access.

Surfaces:

- **Slot-side service** (`services/agent-control`, `cloudbrowser.agent_control`):
  `POST /agent-control/v1` behind the trusted-secret binding lease
  (`X-CB-Trusted-Secret` + `X-CB-Principal`/`X-CB-Browser`/`X-CB-Generation`,
  see `contract.md`); `POST /agent-control/lease` rotates the binding lease.
- **Router relay** (`cloudbrowser.router`): `POST /v1/agent/<operation>` forwards
  allowlisted operations (`tab_open`, `navigate`, `click`, `type`, `page_info`, `tabs_list`)
  from the caller's own active, bound session to that slot's agent-control
  service. Identity, session, slot, browser, and generation are server-derived;
  forbidden operations are refused locally before any network egress.
