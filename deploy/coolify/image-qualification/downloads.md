# Image qualification — downloads

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/downloads:v0.2.0-dev1`
- digest: `sha256:REPLACE_AFTER_CI_BUILD`
- status: pending
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/downloads/Dockerfile`
- runtime port: `8083`
- public host: `cloudfiles2.dev01.pmo.city` (route is step 19)
- non-root: required (`cloudbrowser`, uid 10001)
- healthcheck: required (`GET /health`)
- provenance: required (BuildKit provenance and SBOM)

## Qualification evidence

Populate this record from the immutable CI run and image inspect output. Do
not mark `status` complete from source review alone. Confirm the published
manifest digest, non-root runtime user, healthcheck result, provenance/SBOM
attestations, the durable volume mount, and the attachment-only service
startup check. The release remains `installable: false` until all seven
records are complete and the runtime and security acceptance matrix is
approved.
