# Image qualification — downloads

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/downloads:v0.2.0-dev1`
- digest: `sha256:72dda663b1abf813fd61b90dd3ad196de76a7e29ab4740b176977fb65fb02b59`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/downloads/Dockerfile`
- runtime port: `8083`
- public host: `cloudfiles2.dev01.pmo.city` (route is step 19)
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
container health, runtime UID, and downloads health endpoint. The durable
volume is configured by the Coolify compose. No credentials, cookies, tokens,
passwords, or OTPs are included in this record.
