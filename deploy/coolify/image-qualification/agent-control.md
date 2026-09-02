# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control:v0.2.0-dev1`
- digest: `sha256:c7c48f5feba7c508c050ac218dc16c3486f4ddd20234e1f16fbdf2b987e0657b`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33689715313`
- source commit `03a5565e2ca317a9c18554f876a313b4eb64d9d6`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `03a5565e2ca317a9c18554f876a313b4eb64d9d6` in CI run
`33689715313`, after every matrix job completed successfully. The CI job also
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and restricted agent-control health endpoint.
The agent-control boundary remains restricted to its allowlisted surface. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
