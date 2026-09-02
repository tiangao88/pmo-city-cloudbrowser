# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser:v0.2.0-dev1`
- digest: `sha256:REPLACE_AFTER_CI_BUILD`
- status: pending
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230` (restricted browser API)
- non-root: required (`cloudbrowser`, uid 10001)
- healthcheck: required (`GET /browser/health`)
- provenance: required (BuildKit provenance and SBOM)

## Qualification evidence

Populate this record from the immutable CI run and image inspect output. Do
not mark `status` complete from source review alone. Confirm the published
manifest digest, non-root runtime user, healthcheck result, provenance/SBOM
attestations, and the restricted browser API startup check. Raw CDP and
credential surfaces must remain unavailable. The release remains
`installable: false` until all seven records are complete and the runtime and
security acceptance matrix is approved.
