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

The implementation does not make live changes and does not expose the
internal downloads service as a public host. Public HTML and deployment
wiring remain Phase 3 work.
