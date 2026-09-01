# CloudBrowser deployment

The repository is the source of truth for deployment definitions, but the
bootstrap release is deliberately not installable. A final Compose bundle must
be backed by versioned service contracts, pinned images, health checks,
backup/rollback operations, and side-by-side isolation tests.

Every installation must set a unique `CB_INSTANCE_ID` and derive its network,
volumes, public hostnames, and secret namespaces from that identifier. The
imported `legacy-compose-v2.reference.yaml` is retained for migration
comparison only.
