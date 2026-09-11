# Image qualification — cloudfiles

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/cloudfiles@sha256:4ae6bef7677c667a148e1d1efaf13d3c6de93ba65fd54012a5b96b15ed90fd73`
- digest: `sha256:4ae6bef7677c667a148e1d1efaf13d3c6de93ba65fd54012a5b96b15ed90fd73`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/cloudfiles/Dockerfile`
- runtime port: `8085`
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
