# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer@sha256:0b022e4c350f6f6467c669cef9f0964c0d948c38505269c2565d6c807edf5ccf`
- digest: `sha256:0b022e4c350f6f6467c669cef9f0964c0d948c38505269c2565d6c807edf5ccf`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33827177104`
- source commit `1d9ea90750d6ee4a3e39071fd14650891f06115e`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `1d9ea90750d6ee4a3e39071fd14650891f06115e` in CI run `33827177104`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
