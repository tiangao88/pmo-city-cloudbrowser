# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser@sha256:b9406369d0ba660f785a24c6d0034719c382aa6be465a870a142a3b07d5ee7d4`
- digest: `sha256:b9406369d0ba660f785a24c6d0034719c382aa6be465a870a142a3b07d5ee7d4`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/browser/health`)
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
