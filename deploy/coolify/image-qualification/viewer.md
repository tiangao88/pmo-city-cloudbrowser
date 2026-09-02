# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer:v0.2.0-dev1`
- digest: `sha256:b43d9da6bdf091e63d0bbf4f647ce28e12d6af88b5fb99784fe233615f4043d7`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
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
container health, runtime UID, and bounded viewer health endpoint. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
