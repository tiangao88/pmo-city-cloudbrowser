# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer@sha256:8c3837885c51999cc96cf0542f48a1fff6b585ddca3b75818d485e0b4778b87c`
- digest: `sha256:8c3837885c51999cc96cf0542f48a1fff6b585ddca3b75818d485e0b4778b87c`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34043783268`
- source commit `ad61d9ee2899771c24dda4c4d7cb2438c6445e56`
## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from the published image build for the release commit in CI run `34043783268`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
