# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control@sha256:4dbbd08f3219ff1e5edcc65e033c1a3c4c043c7e21fb8b7d0e4623b9ec7472c0`
- digest: `sha256:4dbbd08f3219ff1e5edcc65e033c1a3c4c043c7e21fb8b7d0e4623b9ec7472c0`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `8e455b4efbbde723c26c47879da1b339ca3835b5`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34603628801`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `8e455b4efbbde723c26c47879da1b339ca3835b5` in CI run
`34603628801`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
