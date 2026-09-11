# Image qualification — browser

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/browser@sha256:7d9569c0435c95f1e696dc6f123b1f0e525e9542cdb8ddb81dac57f97ced58b2`
- digest: `sha256:7d9569c0435c95f1e696dc6f123b1f0e525e9542cdb8ddb81dac57f97ced58b2`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/browser/Dockerfile`
- runtime port: `9230`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/browser/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `face98a96d69443eefbf81516b75525f58b9a62b`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34610008200`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `face98a96d69443eefbf81516b75525f58b9a62b` in CI run
`34610008200`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
