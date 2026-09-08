# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control@sha256:6d1df49a6797808b5dba1b93d577b697cf2f48f924ea01a5df5e9ca591f992b7`
- digest: `sha256:6d1df49a6797808b5dba1b93d577b697cf2f48f924ea01a5df5e9ca591f992b7`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
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
