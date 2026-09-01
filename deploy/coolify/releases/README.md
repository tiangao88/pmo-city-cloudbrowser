# Release manifests

Each release directory contains the exact product/specification/contract
combination and installation namespace. A manifest is installable only when
its images are pinned, health checks exist, migration/rollback are tested, and
its security gates pass.

The `v0.1.0` directory is a deliberately non-installable migration marker.
