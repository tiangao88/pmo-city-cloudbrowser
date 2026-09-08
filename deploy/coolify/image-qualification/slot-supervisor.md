# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor@sha256:7b0ac83c93ba6f11f9af5e7f808990acc0a39c483b5d999261a3add3a72a0df0`
- digest: `sha256:7b0ac83c93ba6f11f9af5e7f808990acc0a39c483b5d999261a3add3a72a0df0`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
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
