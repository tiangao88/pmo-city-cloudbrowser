# ADR-0002: Parallel specifications and code versions

- Status: Accepted as repository bootstrap policy
- Date: 2026-09-01

Specifications evolve in mutable `proposals/vX.Y/` directories and become
immutable `baselines/vX.Y.Z/` snapshots after approval. Code is versioned by
branches, tags, and pinned image digests, not by duplicating source trees per
version. Release manifests bind the selected code, spec baseline, contracts,
and persistent-volume namespace.
