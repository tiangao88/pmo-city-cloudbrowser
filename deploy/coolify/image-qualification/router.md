# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router@sha256:c52595cff60da10a8fd2b52832b9f73774001b71ab3de8bab1b8a9c7a6cda04b`
- digest: `sha256:c52595cff60da10a8fd2b52832b9f73774001b71ab3de8bab1b8a9c7a6cda04b`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34173065983`
- source commit `241667324e901b2c027c97022d764b4bea778afc`
## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from the published image build for the release commit in CI run `34173065983`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
