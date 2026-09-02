# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router:v0.2.0-dev1`
- digest: `sha256:d781f49f934b36bd02e6f5a11ae795ea9d86d5aaab9aa604c92d4c49ce222e92`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33691294596`
- source commit `677deb845ab92fbf54a816f3e7e44af73a2bf352`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `677deb845ab92fbf54a816f3e7e44af73a2bf352` in CI run
`33691294596`, after every matrix job completed successfully. The image config
revision matches the source commit. The CI job also verified the non-root user,
image healthcheck, provenance/SBOM metadata, container health, runtime UID, and
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
