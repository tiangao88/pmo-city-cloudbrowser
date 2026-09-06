# Image qualification — agent-control

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/agent-control@sha256:f630567ba8be5393fd44d9d28bc7132eb71f3df0b5f7a3f866553cf90ff1e466`
- digest: `sha256:f630567ba8be5393fd44d9d28bc7132eb71f3df0b5f7a3f866553cf90ff1e466`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/agent-control/Dockerfile`
- runtime port: `8090`
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
