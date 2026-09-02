# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router:v0.2.0-dev1`
- digest: `sha256:147efd81ac5f4665a9a6f15df37858c7e4d4d41be976b1e54659f026d4ae5d84`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33693777354`
- source commit `5a3d2204165b2662b7a432d30e124999c737b132`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `5a3d2204165b2662b7a432d30e124999c737b132` in CI run
`33693777354`, after every matrix job completed successfully. The image config
revision matches the source commit. The CI job also verified the non-root user,
image healthcheck, provenance/SBOM metadata, container health, runtime UID, and
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
