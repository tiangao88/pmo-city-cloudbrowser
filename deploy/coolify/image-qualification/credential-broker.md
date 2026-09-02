# Image qualification — credential-broker

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/credential-broker:v0.2.0-dev1`
- digest: `sha256:35598e12b4c9e3bbf299fb2c84a988c4f195a676d2d0b35d3937f1fc97b913cb`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/credential-broker/Dockerfile`
- runtime port: `8084`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33670797654`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the `sha-b83620a`
image tag after every Step-17 matrix job completed successfully. The CI job
also verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and status-only broker health endpoint. No live
credential operation was performed as part of this qualification. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
