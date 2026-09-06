# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor@sha256:d271afd0a3a13f08b0c804950561b3642af749db8b4d79e67a4588e015b2efe1`
- digest: `sha256:d271afd0a3a13f08b0c804950561b3642af749db8b4d79e67a4588e015b2efe1`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
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
