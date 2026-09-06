# CloudFiles Phase 2 integration

Phase 2 adds the owner-bound browser-download ingest seam and the typed
internal `downloads/v1` client. The pipeline stages a bounded stream in a
private temporary file, scans it before publication, and sends clean material
to the internal downloads boundary. Non-clean material is kept in the
owner-scoped quarantine namespace and is never published as a retrievable
entry.

## Boundaries

- `IngestPipeline` accepts only a server-derived `PrincipalBinding`; it has no
  `principal_id` or destination-path argument.
- `DownloadsClient` sends an allowlisted shared-secret and binding header set,
  uses a timeout, and caps response bodies.
- `DownloadsStoreAdapter` is the local integration seam for contract tests; the
  production deployment uses the typed HTTP client over the internal network.
- `FakeBrowserDownloadSource` models a completion event without allowing the
  browser event to select a different owner.

## Production browser-download ingest transport

The production transport is an internal authenticated HTTP handoff backed by
the browser's local download directory — consistent with every other
cross-service integration in the runtime (shared-secret auth, allowlisted
binding headers, bounded bodies). No public route and no frozen contract
changes: the downloads `v1` API stays GET-only, and the durable store volume
remains the write path for publication.

- `BrowserDownloadWatcher` (browser service) scans a server-configured
  download directory (`CB_BROWSER_DOWNLOAD_DIR`) and emits only completed
  regular, non-symlink, confined files: `.crdownload` partials, symlinks,
  non-regular entries, unsafe names, and oversized files are never emitted.
  The owner/browser binding is the browser's own server identity; a fresh
  `request_id` is minted per file. Successful submits consume the source
  file; failed submits keep it for the next scan, and the durable store's
  suffixed-name semantics make duplicates safe.
- `IngestClient` (browser side) streams each completed file to the internal
  receiver with the allowlisted header set, an explicit bounded
  `Content-Length`, a timeout, and a capped response.
- `create_ingest_server` (CloudFiles side) is an internal-only authenticated
  listener (`POST /ingest/complete`, `GET /health` open) that resolves the
  binding from allowlisted headers only, rejects oversized or unsafe input
  before/without publication, and feeds the existing scan-before-publish
  `IngestPipeline`. Responses carry only the bounded receipt — never the raw
  principal or any server path. `server_close()` shuts it down cleanly.
- `build_download_watcher` (browser service runtime) wires the watcher to the
  receiver from server configuration (`CB_BROWSER_DOWNLOAD_DIR`,
  `CB_DOWNLOADS_INGEST_URL`, `CB_DOWNLOADS_INGEST_SECRET`) and is inert when
  the transport is not configured; `run_browser_service` starts and closes it
  with the service lifecycle.
- Deployment wiring (still pending): the CloudFiles service must bind
  `create_ingest_server(runtime.pipeline, ...)` on an internal address with a
  trusted-secret env, the browser service must set the three watcher env
  variables plus a real server-derived binding (`CB_PRINCIPAL_ID`,
  `CB_BROWSER_ID`, `CB_PROFILE_ID`, `CB_BINDING_GENERATION`), Chrome must be
  pointed at a watched download directory, and the durable downloads volume
  must be shared with the CloudFiles service. Until that slice lands, the
  transport is component-complete but not active in any deployed
  configuration.

The implementation does not make live changes and does not expose the
internal downloads service or the ingest receiver as a public host. Public
HTML and deployment wiring remain Phase 3 work.
