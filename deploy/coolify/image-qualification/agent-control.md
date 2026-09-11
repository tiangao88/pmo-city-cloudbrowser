# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control@sha256:7d57e6ed5d514c5a6cc005925a7bebae725ee22da0e7119198d74e4cacae7227`
- digest: `sha256:7d57e6ed5d514c5a6cc005925a7bebae725ee22da0e7119198d74e4cacae7227`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `79b739eeae4b44dc28444a7ce05c97c0770e4df0`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34607253841`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `79b739eeae4b44dc28444a7ce05c97c0770e4df0` in CI run
`34607253841`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
