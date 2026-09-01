# CloudBrowser control API v1

This contract is the bounded HTTP control surface for the owner-bound slot
supervisor. It accepts lifecycle intents only; it does not expose raw CDP,
credential material, arbitrary evaluation, filesystem access, or process
control.

## Endpoints

- `GET /health` — bounded service health metadata.
- `POST /control` — accepts `{ "request_id": "opaque-id", "operation": "..." }`.

The allowed operations are `wake`, `suspend`, `stop`, and `recreate`. The
server resolves the profile, principal, browser, tab, and generation binding;
request fields cannot override that binding.

The response contains only `request_id`, `status`, `state`, `restored_count`,
and a bounded non-sensitive `error_code`. It never contains page values,
credential material, cookies, storage values, network bodies, raw exceptions,
or CDP payloads.

This slice is implemented in `cloudbrowser.router.control_api` and remains
subject to the full v1 authentication, queue, and runtime acceptance matrix.
