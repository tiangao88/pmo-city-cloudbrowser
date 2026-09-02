# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control:v0.2.0-dev1`
- digest: `sha256:4118dd4768a23f7b350aa723b0a2d87f96924afd9e45a2a58c600ac97f06d52d`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
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
container health, runtime UID, and restricted agent-control health endpoint.
The agent-control boundary remains restricted to its allowlisted surface. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
