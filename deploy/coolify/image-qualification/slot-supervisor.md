# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor:v0.2.0-dev1`
- digest: `sha256:3bada0e9c63dbc021aea70193e5f1d227cada7fe2e56482c44d8381f29213d0c`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33689715313`
- source commit `03a5565e2ca317a9c18554f876a313b4eb64d9d6`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `03a5565e2ca317a9c18554f876a313b4eb64d9d6` in CI run
`33689715313`, after every matrix job completed successfully. The CI job also
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
