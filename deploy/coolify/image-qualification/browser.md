# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser:v0.2.0-dev1`
- digest: `sha256:4d652f8c6feaaa5a494764442e759aacd7a013251113bf6df12e58a5ec251ca5`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230` (restricted browser API)
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /browser/health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33670797654`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the `sha-b83620a`
image tag after every Step-17 matrix job completed successfully. The CI job
also verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and restricted browser health endpoint. Raw CDP
and credential surfaces were not exposed by the qualification check. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
