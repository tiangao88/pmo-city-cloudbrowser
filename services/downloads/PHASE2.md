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
- Source deployment wiring is present in the current service entrypoints and
  Compose: a private ingest listener, browser watcher URL/secret/directory,
  runtime binding and durable storage. Qualify the actual browser download,
  scan and local attachment journey against current images before making a
  deployed-product claim.

The internal downloads service and ingest receiver are private. Public HTML is
implemented by CloudFiles. See the
[status register](../../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md) for current
evidence and the [roadmap](../../specs/proposals/v0.2/ROADMAP.md) for qualification.
