# CloudBrowser runtime services

The repository contains independently deployable service images. The current
release includes router, slot-supervisor, browser, viewer, agent-control,
downloads, and credential-broker. The public CloudFiles gateway is introduced
as a separate service in the later delivery phase.

## CloudFiles Phase 2 integration

Phase 2 adds the owner-bound browser-download ingest seam and the typed
internal `downloads/v1` client. The pipeline stages a bounded stream in a
private temporary file, scans it before publication, and sends clean material
to the internal downloads boundary. Non-clean material is kept in the
owner-scoped quarantine namespace and is never published as a retrievable
entry.

- `IngestPipeline` accepts only a server-derived `PrincipalBinding`; it has no
  `principal_id` or destination-path argument.
- `DownloadsClient` sends an allowlisted shared-secret and binding header set,
  uses a timeout, and caps response bodies.
- `DownloadsStoreAdapter` is the local integration seam for contract tests; the
  production deployment uses the typed HTTP client over the internal network.
- `FakeBrowserDownloadSource` models a completion event without allowing the
  browser event to select a different owner.

## Production browser-download ingest transport

See `services/downloads/PHASE2.md`. In short: the browser service's
`BrowserDownloadWatcher` emits only completed, regular, confined files from
the server-configured download directory (`CB_BROWSER_DOWNLOAD_DIR`) under its
own server binding; `IngestClient` streams them over the internal network to
the CloudFiles ingest receiver (`create_ingest_server`, `POST
/ingest/complete`, trusted-secret auth, allowlisted `X-CB-*` headers, bounded
Content-Length, capped responses); the receiver feeds the existing
scan-before-publish `IngestPipeline`. Public routes and the downloads `v1`
contract remain unchanged.

> The transport is component-complete and green under contract/integration
> tests, but the deployment wiring (receiver bound in the CloudFiles service,
> watcher env + real server binding on the browser service, shared downloads
> volume, Chrome download directory) is a pending slice — see PHASE2.md. It is
> not yet active in any deployed configuration.

The implementation does not make live changes and does not expose the
internal downloads service as a public host. Public HTML and deployment
wiring remain Phase 3 work.
