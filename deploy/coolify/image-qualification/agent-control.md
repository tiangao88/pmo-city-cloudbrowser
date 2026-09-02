# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control:v0.2.0-dev1`
- digest: `sha256:ab428bf50ccde5f45e67d9b987f73c8c698bef4c8337f62e9acb090b4fa37b08`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
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
restricted agent-control health endpoint. The agent-control boundary remains
restricted to its allowlisted surface. No credentials, cookies, tokens,
passwords, or OTPs are included in this record.
