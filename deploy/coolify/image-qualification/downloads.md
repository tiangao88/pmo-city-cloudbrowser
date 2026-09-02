# Image qualification — downloads

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/downloads:v0.2.0-dev1`
- digest: `sha256:060083d77163286f2ad22d73287e9f9e95aa85e3aa03e1292369c7c49472593e`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/downloads/Dockerfile`
- runtime port: `8083`
- public host: `cloudfiles2.dev01.pmo.city` (route is step 19)
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
container health, runtime UID, and downloads health endpoint. The durable
volume is configured by the Coolify compose. No credentials, cookies, tokens,
passwords, or OTPs are included in this record.
