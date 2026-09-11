# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer@sha256:4a528717031e5cc9679ea430ee95fe7000266ffe39e3c52ba96f3bfe68880b3b`
- digest: `sha256:4a528717031e5cc9679ea430ee95fe7000266ffe39e3c52ba96f3bfe68880b3b`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
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
