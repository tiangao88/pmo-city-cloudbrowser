# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor@sha256:c7909c9b6295186e4a4690e498e4582d89bec0e06edbd0a7acbe6571b7d2cc85`
- digest: `sha256:c7909c9b6295186e4a4690e498e4582d89bec0e06edbd0a7acbe6571b7d2cc85`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34004823087`
- source commit `0a55001bf905d2441dee4580f9593643e1fa2236`
## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from the published image build for the release commit in CI run `34004823087`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
