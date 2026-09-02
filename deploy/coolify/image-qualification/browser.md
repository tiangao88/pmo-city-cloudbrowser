# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser:v0.2.0-dev1`
- digest: `sha256:91ebcf31e2b06abb44da258cccb51c6f88cd503b5d39ed75754c940b5ea9bb3b`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230` (restricted browser API)
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /browser/health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33689715313`
- source commit `03a5565e2ca317a9c18554f876a313b4eb64d9d6`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `03a5565e2ca317a9c18554f876a313b4eb64d9d6` in CI run
`33689715313`, after every matrix job completed successfully. The CI job also
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and restricted browser health endpoint. Raw CDP
and credential surfaces were not exposed by the qualification check. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
