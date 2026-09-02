# Release manifests

Each release directory contains the exact product/specification/contract
combination and installation namespace. A manifest is installable only when
its images are pinned, health checks exist, migration/rollback are tested, and
its security gates pass.

The `v0.1.0` directory is a deliberately non-installable migration marker.
The `v0.2.0-dev1` directory is the first digest-pinned, installable release
manifest, based on the verified Step-17 CI qualification run. Coolify
installation and staging/runtime qualification are Step 19 and require
explicit approval.
