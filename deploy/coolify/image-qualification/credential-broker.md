# Image qualification — credential-broker

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/credential-broker@sha256:46a6d68cea33a8bc5702b19e6c7136ab45586fb8b4b74ef8c5e57a03c3d49e5f`
- digest: `sha256:46a6d68cea33a8bc5702b19e6c7136ab45586fb8b4b74ef8c5e57a03c3d49e5f`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/credential-broker/Dockerfile`
- runtime port: `8084`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34246186158`
- source commit `fd3985ba0d247f17139a484fa8e6e3a0aa6f1226`
## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from the published image build for the release commit in CI run `34231460028`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
