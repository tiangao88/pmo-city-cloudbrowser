# Image qualification — slot-supervisor

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/slot-supervisor:v0.2.0-dev1`
- digest: `sha256:REPLACE_AFTER_CI_BUILD`
- status: pending
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/slot-supervisor/Dockerfile`
- runtime port: `8081`
- non-root: required (`cloudbrowser`, uid 10001)
- healthcheck: required (`GET /health`)
- provenance: required (BuildKit provenance and SBOM)

## Qualification evidence

Populate this record from the immutable CI run and image inspect output. Do
not mark `status` complete from source review alone. Confirm the published
manifest digest, non-root runtime user, healthcheck result, provenance/SBOM
attestations, and the service startup check. The release remains
`installable: false` until all seven records are complete and the runtime and
security acceptance matrix is approved.
