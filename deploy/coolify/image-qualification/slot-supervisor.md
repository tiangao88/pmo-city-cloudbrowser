# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor:v0.2.0-dev1`
- digest: `sha256:78c814b42188835782e00d01fd7422673cde53ce1aad042a6b65ffddc6361725`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
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
container health, runtime UID, and service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
