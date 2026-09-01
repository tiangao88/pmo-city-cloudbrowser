# CloudBrowser service images

Each service has a separate entry point and image definition. The current
`v0.2.0-dev1` images provide a dependency-free, non-sensitive health/ready
surface while product endpoints are extracted behind their versioned
contracts. They are source-built for validation and are not installable until
published, pinned, and accepted by the runtime/security matrix.

The services deliberately do not copy or mount `legacy/` at runtime. The
legacy tree remains migration/reference material only.

## Local validation

```bash
uv run make check
```

The local bundle can be inspected with a Compose implementation supporting the
Compose specification. The development host may not have a running Docker
engine; in that case image builds and container health must be exercised in CI
or a Coolify staging environment before an installable release is claimed.

## Build and publish

The manually triggered or `v0.2.0-dev*` tag-triggered `Build images` workflow
builds each service image with Buildx and publishes provenance/SBOM metadata.
Publishing images does not by itself make a release installable; the release
manifest must contain immutable digests and the runtime/security acceptance
matrix must pass.
