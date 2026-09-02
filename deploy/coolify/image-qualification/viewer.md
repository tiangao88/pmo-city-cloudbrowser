# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer:v0.2.0-dev1`
- digest: `sha256:399d5f428e773a043d9f23bd579651f9a27710ddaa318cd01978c166bb9e59fa`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33684797404`
- source commit `d640b56fb66fe49f2d944c21cbdd4fc88b681b42`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `d640b56fb66fe49f2d944c21cbdd4fc88b681b42` in CI run
`33684797404`, after every matrix job completed successfully. The CI job also
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and bounded viewer health endpoint. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
