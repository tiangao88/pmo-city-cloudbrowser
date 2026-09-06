# CloudBrowser control API v1

This contract is the bounded HTTP control surface for the owner-bound router
control plane. It accepts session and lifecycle intents only; it does not
expose raw CDP, credential material, arbitrary evaluation, filesystem access,
or process control.

## Router endpoints (implemented in `cloudbrowser.router.router_api`)

- `GET /health`, `GET /ready` — bounded service health metadata.
- `POST /v1/session` — enqueue or refresh the caller's own session. Identity is
  resolved server-side through the identity-link service; the response carries
  only `request_id`, `session_id`, `status`, optional `slot_id`, and offer or
  session TTLs. It never contains principal IDs, emails, or binding values.
- `GET /v1/session` — the caller's own current session in the same bounded shape.
- `POST /v1/session/leave` — leave the caller's own session.
- `POST /v1/slot/<slot_id>/<operation>` — wake, suspend, or recreate a slot the
  caller's own active session is bound to; forwarded to the slot supervisor over
  the trusted-secret channel.
- `POST /v1/agent/<operation>` — relay one allowlisted page action
  (`navigate`, `click`, `type`, `page_info`, `tabs_list`) to the caller's own
  assigned slot's agent-control service. Forbidden operations
  (`raw_cdp`, `evaluate`, `cookies`, `storage`, `network`, `filesystem`,
  `process`, `credential_material`, `password_values`) are refused locally;
  unknown operations return `operation_not_supported`. See
  `../agent-control/v1/contract.md` for the downstream seam.

Failures are bounded envelopes `{"request_id", "status": "failed",
"error_code"}` with stable codes (`unauthorized`, `session_not_found`,
`no_binding`, `unknown_slot`, `capability_denied`, `operation_not_supported`,
`invalid_request`, `agent_unavailable`, `supervisor_unavailable`); they never
include principal IDs, binding values, page text, or raw exception text.

## Slot supervisor endpoints (implemented in `cloudbrowser.router.control_api`)

- `GET /health` — bounded service health metadata.
- `POST /control` — accepts `{ "request_id": "opaque-id", "operation": "..." }`.

The allowed operations are `wake`, `suspend`, `stop`, and `recreate`. The
server resolves the profile, principal, browser, tab, and generation binding;
request fields cannot override that binding.

The response contains only `request_id`, `status`, `state`, `restored_count`,
and a bounded non-sensitive `error_code`. It never contains page values,
credential material, cookies, storage values, network bodies, raw exceptions,
or CDP payloads.

This slice is subject to the full v1 authentication, queue, and runtime
acceptance matrix.
