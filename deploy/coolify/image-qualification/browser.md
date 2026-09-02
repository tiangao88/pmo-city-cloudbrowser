# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser:v0.2.0-dev1`
- digest: `sha256:9cdcbe75a401390ed854f85a78cfde66699a9cfa43137513dc2a7bc31b1b4c9e`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230` (restricted browser API)
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /browser/health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33691294596`
- source commit `677deb845ab92fbf54a816f3e7e44af73a2bf352`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `677deb845ab92fbf54a816f3e7e44af73a2bf352` in CI run
`33691294596`, after every matrix job completed successfully. The image config
revision matches the source commit. The CI job also verified the non-root user,
image healthcheck, provenance/SBOM metadata, container health, runtime UID, and
restricted browser health endpoint. Raw CDP and credential surfaces were not
exposed by the qualification check. No credentials, cookies, tokens, passwords,
or OTPs are included in this record.
