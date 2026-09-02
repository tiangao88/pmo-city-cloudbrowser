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

## Allowed operations

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
