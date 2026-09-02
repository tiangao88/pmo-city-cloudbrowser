# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router:v0.2.0-dev1`
- digest: `sha256:c56259d639e2e4a65bd5ec80efa6344cc97a9282d2ff562fa2ba7ab9af212b97`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
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
