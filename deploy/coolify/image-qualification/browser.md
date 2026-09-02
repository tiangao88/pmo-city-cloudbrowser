# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser:v0.2.0-dev1`
- digest: `sha256:e97a1cc3e264436955c94d037d7116eb840f883662fcd703053908eddbc3bd18`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230` (restricted browser API)
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /browser/health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33684797404`
- source commit `d640b56fb66fe49f2d944c21cbdd4fc88b681b42`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `d640b56fb66fe49f2d944c21cbdd4fc88b681b42` in CI run
`33684797404`, after every matrix job completed successfully. The CI job also
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and restricted browser health endpoint. Raw CDP
and credential surfaces were not exposed by the qualification check. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
