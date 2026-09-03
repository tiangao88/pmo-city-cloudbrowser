# CloudFiles threat model (Phase 0)

> Version: **v0.2 development proposal — 2026-09-03**
> Status: **PROPOSED — Phase 0 boundary document**

This threat model identifies the realistic attacker capabilities against the
CloudFiles product and the security invariants the implementation must hold.
It maps each threat to a focused red test that must fail before Phase 1
production code is written.

## Trust model

Actors:

- **Employee A** — the legitimate principal; identity verified by TinyAuth and
  PMO City SSO; may list and download only their own files.
- **Employee B** — a different legitimate principal; same verification path.
- **Internal microservice** — gateway or worker; holds the
  `CB_DOWNLOADS_SHARED_SECRET`; not exposed to the public network.
- **Public attacker** — unauthenticated, on the internet; cannot present
  TinyAuth or shared secrets.
- **Compromised legacy component** — historical deployments contained
  credential-material access; the new product must not inherit those risks.

Public trust boundary:

```text
[Client] --TinyAuth--> [CloudFiles gateway] --trusted secret--> [downloads]
```

The CloudFiles gateway is the only public trust termination. The downloads
service is internal.

## Threats and security invariants

### T1 — Forged public identity

- **Threat:** Attacker supplies `Remote-Email: victim@…` (or `X-CB-Principal`)
  and bypasses TinyAuth, or spoofs another principal.
- **Invariant:** No client-supplied identity header may influence binding. The
  gateway must derive the principal exclusively from the TinyAuth session.
- **Red test:** forged `Remote-Email` and `X-CB-Principal` must yield
  `owner_binding_unavailable` or `unauthorized`, never the victim’s listing.

### T2 — Cross-principal read

- **Threat:** Principal A requests `/api/files` or `/file/<name>` and receives
  principal B’s data.
- **Invariant:** All file paths resolve under
  `<store_root>/<principal_id>/<entries>/<safe-name>`. The principal key is the
  server-bound `principal_id`, not the path. Cross-owner attempts return
  `forbidden_owner_mismatch`.
- **Red test:** A request bound to principal A that names a file under B’s
  area must be rejected.

### T3 — Stale, revoked, or missing binding

- **Threat:** An attacker replays an old session or invokes the gateway when
  the identity provider cannot resolve the subject.
- **Invariant:** Missing, ambiguous, revoked, or stale binding → fail closed
  with `owner_binding_unavailable`.
- **Red test:** NoTinyAuth, expired-token, and unknown-subject cases return
  `owner_binding_unavailable` or `unauthorized`.

### T4 — Path traversal and unsafe filenames

- **Threat:** A name containing `..`, `/`, `\`, control characters, or
  symlinks lets the requester escape the owner area.
- **Invariant:** `safe_name(name)` returns `None` for any unsafe name. The
  store rejects traversal at the filesystem level (`O_NOFOLLOW`, `realpath`
  check, no parent links).
- **Red test:** Names like `../owner-b/x`, `a/b`, `.hidden`, `name%0ACRLF`,
  and `name\x00x` must raise `invalid_name`.

### T5 — Header injection via filename

- **Threat:** Filenames with CR/LF or quote characters break response
  parsers and proxies.
- **Invariant:** `Content-Disposition` and `Content-Type` use allowlisted
  characters; names are validated against a printable ASCII subset, then
  escaped.
- **Red test:** A filename containing `\r\n` or a quote must be rejected
  before any header is written.

### T6 — Direct downloads exposure

- **Threat:** The downloads container is reachable from the public network;
  attackers bypass the gateway.
- **Invariant:** `cloudfiles2.dev01.pmo.city` must terminate at the gateway.
  Direct routing to the downloads container is forbidden. The downloads
  container binds only to internal network interfaces.
- **Red test:** Compose/manifest review and integration tests must prove no
  public host resolves to the downloads container.

### T7 — Identity leak in error/listing

- **Threat:** Error envelopes echo the raw `Remote-Email`, the principal id,
  internal paths, or include shared-secret names.
- **Invariant:** Public responses never include raw identity strings, paths,
  or shared-secret names. Bounded `error_code` + `request_id` only.
- **Red test:** Server-side snapshot of every public response and error path
  is inspected; identity strings and paths must be absent.

### T8 — Quarantine retrieval

- **Threat:** A file flagged by ClamAV is still returned to the employee via
  the public surface.
- **Invariant:** Quarantined files live outside the retrievable namespace and
  are never returned by `/api/files` or `/file/<name>`.
- **Red test:** A file in `quarantine/` must not appear in `/api/files` and
  any direct read attempt must return `not_found`.

### T9 — Quota/retention tampering

- **Threat:** A principal writes or retains files past quota or age.
- **Invariant:** Quota enforcement precedes file publication; retention
  decisions are deterministic against an injected clock.
- **Red test:** A file exceeding quota must not be published; files older than
  retention must be purged and not retrievable.

### T10 — GDPR erasure regression

- **Threat:** Erasure operation leaves copies of the principal’s data in
  quarantine, audit, or temp paths.
- **Invariant:** Erasure removes all references to the principal under the
  instance root and emits a redacted audit event.
- **Red test:** After erasure, the principal’s area is empty, quarantine empty,
  and no paths survive.

### T11 — Replay via stale binding headers

- **Threat:** Gateway forwards `X-CB-*` headers from the public request.
- **Invariant:** The gateway strips and replaces all `X-CB-*` headers before
  calling downloads; only the gateway may set them.
- **Red test:** Client-supplied `X-CB-Principal: <other>` does not affect the
  internal call.

### T12 — Excessive payload

- **Threat:** A malicious download saturates the gateway with very large files
  or unbounded streams.
- **Invariant:** Bounded file size, bounded stream length, bounded rate. Files
  larger than the configured maximum yield `too_large` and never enter
  storage.
- **Red test:** A stream larger than the limit is rejected before reaching the
  final storage path.

### T13 — Symlink and special-file escape

- **Threat:** Owner area contains a symlink or special file that the store
  follows into another principal’s area.
- **Invariant:** Storage never follows symlinks (`O_NOFOLLOW`); entries are
  regular files only; listing skips anything that is not a regular file.
- **Red test:** Creating a symlink inside the owner area and attempting to
  read it must raise `invalid_name` or return `not_found`.

### T14 — Log and audit leakage

- **Threat:** Operator logs, audit events, or telemetry contain filenames,
  request bodies, or identity strings.
- **Invariant:** Logs and audit events record `request_id`, bounded codes,
  and counts; never raw names, paths, principal identifiers, or file contents.
- **Red test:** Log/audit capture is exercised across the gateway and
  downloads and inspected for forbidden fields.

### T15 — Direct public download URL reuse

- **Threat:** A signed or leaked URL allows direct public download bypassing
  TinyAuth.
- **Invariant:** No public route returns files without TinyAuth + server
  binding. There are no presigned URLs.
- **Red test:** A request with a missing or invalid TinyAuth session must be
  rejected with `unauthorized`.

## Mapping to Phase 0 red tests

The threats above drive the red tests in
`specs/proposals/v0.2/93-cloudfiles-phase0-red-tests.md`. Each red test must be
observed failing for the intended reason before Phase 1 production code is
written. After Phase 0 closes, those tests become the boundary invariant suite
that subsequent phases extend.

## Phase 0 exit criteria (recap)

- this matrix and the route/response matrix are accepted;
- the red tests exist and have actually failed;
- every threat above is covered by at least one red test;
- no production code has been written prematurely.
