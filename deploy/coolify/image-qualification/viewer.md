# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer@sha256:8232024cc2d3ebdade52bf8b2cc014d8bedb0585c3a8c27b63b17ae3d4592bc0`
- digest: `sha256:8232024cc2d3ebdade52bf8b2cc014d8bedb0585c3a8c27b63b17ae3d4592bc0`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `face98a96d69443eefbf81516b75525f58b9a62b`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34610008200`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `face98a96d69443eefbf81516b75525f58b9a62b` in CI run
`34610008200`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
