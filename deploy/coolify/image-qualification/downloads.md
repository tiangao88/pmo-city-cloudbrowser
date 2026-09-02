# Image qualification — downloads

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/downloads:v0.2.0-dev1`
- digest: `sha256:b2deaec9b7a6709f584d07d00abba77b09911b598249b319cd0c427c17b32f42`
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
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33693777354`
- source commit `5a3d2204165b2662b7a432d30e124999c737b132`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `5a3d2204165b2662b7a432d30e124999c737b132` in CI run
`33693777354`, after every matrix job completed successfully. The image config
revision matches the source commit. The CI job also verified the non-root user,
image healthcheck, provenance/SBOM metadata, container health, runtime UID, and
downloads health endpoint. The durable volume is configured by the Coolify
compose. No credentials, cookies, tokens, passwords, or OTPs are included in
this record.
