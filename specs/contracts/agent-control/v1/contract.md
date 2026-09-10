# Agent Control API v1

Agent control is **page state only**, page-state-oriented, and owner-bound. It
is not a general CDP or process-control channel. The service runs one request
against the server-derived principal, browser, and generation binding.

## Request envelope

```json
{
  "request_id": "opaque-request-id",
  "operation": "page_info|tabs_list|navigate|click|type",
  "params": {}
}
```

The caller does not supply an authoritative principal, profile, slot, browser,
or generation. Those values are derived by the authenticated router and bound to
the selected owner's browser before the request reaches this service.

## Binding lease (authenticated router forwarding seam)

Every request to `POST /agent-control/v1` must carry the trusted router shared
secret (`X-CB-Trusted-Secret`) **and** a per-request server-derived binding
envelope: `X-CB-Principal`, `X-CB-Browser`, and `X-CB-Generation`. The service
accepts the envelope only alongside the trusted secret, and accepts the secret
only when the envelope matches the server-owned binding exactly. Missing,
malformed (empty, oversized, or control-character-bearing), or mismatched
envelope values yield `401 unauthorized` and the request is never dispatched.
The envelope is the authenticated router-to-agent-control forwarding seam.
The router's `AgentControlForwarder` (configured via `CB_AGENT_CONTROL_URLS`
and `CB_AGENT_CONTROL_SHARED_SECRET`, minimum 16 characters) relays only the
allowlisted operations below to slots the caller owns; the caller's identity,
session, slot, browser, and generation are all server-derived. Unknown
slots, sessions without a binding, or slots outside the configured forwarding
map fail closed without network egress. Health (`GET /health`) remains
unauthenticated.

## Exact-target page operations

Every agent page action (`navigate`, `click`, `type`, and `page_info`) must carry
`target_tab_id`; missing, unknown, or stale targets fail closed. `tabs_list` is
the only operation that enumerates tabs and returns Chrome's bounded target IDs.
The browser sidecar resolves the requested ID under a per-target lock and never
falls back to the first page. Page-info URL, title, and text are bounded in the
page JavaScript expression and re-validated at the browser, HTTP, agent-control,
and router/viewer boundaries; oversized values are rejected, never truncated.

The baseline surface may expose:

- `navigate` to an absolute HTTP(S) URL without userinfo, fragments, or path
  traversal;
- `click` with a bounded selector;
- `type` with a bounded selector and text value;
- `page_info` returning bounded URL, title, and text-first page state;
- `tabs_list` returning bounded owner-browser tab metadata.

Actions are mediated by a narrow browser capability. They do not provide a raw
CDP socket or arbitrary JavaScript execution.

## Response envelope

Success is bounded and contains `request_id`, `status: "ok"`, and only the
result needed by the selected operation. Failure is bounded to `status` and a
stable `error_code`; it does not echo selectors, URLs, page text, or exception
text.

## Mandatory denials

The service must reject attempts to access:

- credential material, password values, OTP seeds/codes, grant files;
- cookie values or storage values;
- network bodies or authorization headers;
- raw CDP or unrestricted runtime evaluation;
- filesystem, process control, host/container metadata, or another principal's
  browser, profile, slot, or tab.

Responses must be bounded and safe for model context. Denial details must not
include the requested secret or raw exception text.
