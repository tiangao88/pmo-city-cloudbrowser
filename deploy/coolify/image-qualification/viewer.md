# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer@sha256:06a9cae3c742754d1d90364e364ab58e16ccb6474f1b6576d44bc0ddce7f82c1`
- digest: `sha256:06a9cae3c742754d1d90364e364ab58e16ccb6474f1b6576d44bc0ddce7f82c1`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
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
