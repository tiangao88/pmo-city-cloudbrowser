# Agent Control API v1

Agent control is page-state-oriented and owner-bound. It is not a general CDP
or process-control channel.

## Allowed operations

The baseline surface may expose navigation, bounded interaction, text-first page
state, screenshots on request, owner-browser tab operations, and access to the
owner's durable downloads according to policy.

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
