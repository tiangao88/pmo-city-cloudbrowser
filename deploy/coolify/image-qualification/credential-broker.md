# Image qualification — credential-broker

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/credential-broker:v0.2.0-dev1`
- digest: `sha256:8de77affcff79e1b5956b77003c53c0c664dd08e2b81adfe2f89f0091c84af21`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/credential-broker/Dockerfile`
- runtime port: `8084`
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
status-only broker health endpoint. No live credential operation was performed
as part of this qualification. No credentials, cookies, tokens, passwords, or
OTPs are included in this record.
