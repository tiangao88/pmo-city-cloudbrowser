# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser@sha256:009dd8160bdbbc21f68123d87a94b33dd1b2cfc385bf891d12c8fcb302f83e58`
- digest: `sha256:009dd8160bdbbc21f68123d87a94b33dd1b2cfc385bf891d12c8fcb302f83e58`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `79b739eeae4b44dc28444a7ce05c97c0770e4df0`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34607253841`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `79b739eeae4b44dc28444a7ce05c97c0770e4df0` in CI run
`34607253841`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
