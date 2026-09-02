# Image qualification — credential-broker

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/credential-broker:v0.2.0-dev1`
- digest: `sha256:33b009bdc1aa718b51cf7c1ec8b2b7ea0548193892fc3fb18c07bbba35c67746`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/credential-broker/Dockerfile`
- runtime port: `8084`
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
container health, runtime UID, and status-only broker health endpoint. No live
credential operation was performed as part of this qualification. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
