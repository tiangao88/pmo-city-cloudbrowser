# Agent-control service

The agent-control service exposes the `agent-control/v1` owner-bound, page-state
surface. It accepts only bounded navigation, interaction, page-state, and tab
listing operations for the server-derived browser binding.

The service must receive `CB_PRINCIPAL_ID`, `CB_BROWSER_ID`, and
`CB_BINDING_GENERATION` from the authenticated control plane. These are not
caller-authoritative request fields. The browser-side callbacks are intentionally
narrow; raw CDP, arbitrary runtime evaluation, credentials, cookie/storage
values, network bodies, filesystem, and process control are not available.

The current development runtime wires readiness and URL-only tab listing through
the trusted browser transport. Concrete click, typing, and text extraction
adapters are explicit future integration points; they fail closed until wired.

This is a source-built development slice. It does not claim an installable
release or live deployment.
