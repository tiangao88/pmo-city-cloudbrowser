# Image qualification — cloudfiles

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/cloudfiles@sha256:586bb77d808d3f429866f3eb33ce94c386347acf09dc1550f240dcb2bbca97f1`
- digest: `sha256:586bb77d808d3f429866f3eb33ce94c386347acf09dc1550f240dcb2bbca97f1`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/cloudfiles/Dockerfile`
- runtime port: `8085`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `9544af1952b264f8f896ddd044da92451fda6a4a`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34600527917`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `9544af1952b264f8f896ddd044da92451fda6a4a` in CI run
`34600527917`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
