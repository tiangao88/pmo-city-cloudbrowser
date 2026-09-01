# Release manifests

Each release directory contains the exact product/specification/contract
combination and installation namespace. A manifest is installable only when
its images are pinned, health checks exist, migration/rollback are tested, and
its security gates pass.

The `v0.1.0` directory is a deliberately non-installable migration marker.
The `v0.2.0-dev1` directory is a source-built development scaffold: it has
service images, health checks, and scoped operations for validation, but remains
non-installable until images are published and the runtime/security acceptance
matrix is green.
