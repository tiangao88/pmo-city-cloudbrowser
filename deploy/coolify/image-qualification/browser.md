# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser:v0.2.0-dev1`
- digest: `sha256:5f00814037f4e260a001088a0e1fccd1cf66cefd0d22ba6422e72cd24f9af0c5`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230` (restricted browser API)
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /browser/health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33693777354`
- source commit `5a3d2204165b2662b7a432d30e124999c737b132`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `5a3d2204165b2662b7a432d30e124999c737b132` in CI run
`33693777354`, after every matrix job completed successfully. The image config
revision matches the source commit. The CI job also verified the non-root user,
image healthcheck, provenance/SBOM metadata, container health, runtime UID, and
restricted browser health endpoint. Raw CDP and credential surfaces were not
exposed by the qualification check. No credentials, cookies, tokens, passwords,
or OTPs are included in this record.
