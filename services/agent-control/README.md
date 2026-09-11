# Agent-control service

The service exposes the owner-bound `agent-control/v1` interface. The router
supplies an authenticated binding envelope; lease rotation follows the
server-minted principal/browser/generation. Browser readiness is checked against
the binding around each operation.

Implemented operations are `tab_open`, `tabs_list`, `navigate`, `click`, `type`,
and `page_info`. `tab_open` is the fresh-browser bootstrap: it accepts one
bounded HTTP(S) URL and returns the exact Chromium target ID. Other page actions
require that exact `target_tab_id`; enumeration
returns bounded Chrome target IDs. Concrete CDP page adapters now exist for
navigation, ordinary selector interaction, and bounded text inspection.
Credential fields and broker-only operations remain outside the agent surface.

Raw CDP, unrestricted evaluation, cookie/storage reads, network bodies,
filesystem and process control are unavailable through this API. These are
enforced requirements whose end-to-end qualification must accompany each release.

See the [current contract](../../specs/contracts/agent-control/v1/contract.md),
`src/cloudbrowser/agent_control.py`, and
`src/cloudbrowser/browser_slots/page_actions.py`. Current qualification and
qualification status is in
[implementation status](../../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md).
