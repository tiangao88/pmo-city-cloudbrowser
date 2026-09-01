# Placeholder service images

Dockerfiles and entry points are intentionally not generated from the legacy
implementation. Each service must be extracted under test-first development
and receive its own health check, contract tests, image provenance, and
release-manifest pin before becoming installable.
