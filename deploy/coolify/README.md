# CloudBrowser deployment

The repository is the source of truth for deployment definitions. The
bootstrap release is deliberately non-installable; the `v0.2.0-dev1` bundle
is a source-built development scaffold and is also non-installable until its
images are published, pinned, and accepted. A final Compose bundle must be
backed by versioned service contracts, pinned images, health checks,
backup/rollback operations, and side-by-side isolation tests.

Every installation must set a unique `CB_INSTANCE_ID` and derive its network,
volumes, public hostnames, and secret namespaces from that identifier. The
imported `legacy-compose-v2.reference.yaml` is retained for migration
comparison only.
