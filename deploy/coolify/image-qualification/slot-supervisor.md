# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor@sha256:4e056fa813a4b20f99ce5a303e4d582c51167894cd6a48f5fa54aef1c5608ad5`
- digest: `sha256:4e056fa813a4b20f99ce5a303e4d582c51167894cd6a48f5fa54aef1c5608ad5`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `9544af1952b264f8f896ddd044da92451fda6a4a`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34600527917`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `9544af1952b264f8f896ddd044da92451fda6a4a` in CI run
`34600527917`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
