# Image qualification — cloudfiles

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/cloudfiles:v0.2.0-dev1`
- digest: `sha256:REPLACE_BEFORE_IMAGE_QUALIFICATION`
- status: pending (Phase 5 CI qualification; no digest published yet)
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/cloudfiles/Dockerfile`
- runtime port: `8085`
- public host: `cloudfiles2.dev01.pmo.city` (route is a separate Phase 6 step)
- non-root: passed (image runs as `cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: pending Phase 5 qualification run
- source commit: pending Phase 5 qualification commit

## Qualification evidence

The immutable digest will be resolved from the GHCR manifest for the image built
from the Phase 5 source commit in the Phase 5 CI run, after every matrix job
completes successfully. The image config revision must match the source commit.
The CI job verifies the non-root user, image healthcheck, provenance/SBOM
metadata, container health, runtime UID, and the cloudfiles `/health` endpoint.
The public gateway talks to the internal downloads service only; the downloads
container is never exposed as a public host. No credentials, cookies, tokens,
passwords, or OTPs are included in this record.
