# CloudBrowser runtime service extraction

The `v0.2.0-dev1` runtime is assembled as six separately defined service
images:

- `router` — control-plane entrypoint;
- `slot-supervisor` — owner-bound lifecycle and slot orchestration;
- `browser` — Chromium process and restricted browser transport;
- `viewer` — user-facing viewer boundary;
- `downloads` — durable download boundary;
- `credential-broker` — status-only credential boundary.

Each service has an independent entrypoint, Dockerfile, non-root image user,
healthcheck, and instance-scoped Compose wiring. Runtime code is built only
from `src/` and its service entrypoint; the imported `legacy/` tree is not
mounted or imported.

The browser service is the first fully exercised runtime vertical slice. The
other service endpoints remain bounded health surfaces until their respective
product contracts are implemented. This is an extraction/dev release, not an
installable production release: the manifest remains `installable: false`
until immutable images, provenance, and the complete runtime/security matrix
are accepted.
