# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control:v0.2.0-dev1`
- digest: `sha256:ef701b5a7939b89cc11efdfd2dd5f49812b812ac73923d49159839017fff5573`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
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
restricted agent-control health endpoint. The agent-control boundary remains
restricted to its allowlisted surface. No credentials, cookies, tokens,
passwords, or OTPs are included in this record.
