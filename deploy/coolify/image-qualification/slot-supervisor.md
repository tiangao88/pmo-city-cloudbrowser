# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor@sha256:0cf42668f8e5ea7f33383a5640a01ec09567ed54685053097cc7bcbf5ad373aa`
- digest: `sha256:0cf42668f8e5ea7f33383a5640a01ec09567ed54685053097cc7bcbf5ad373aa`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
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
