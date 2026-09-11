# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router@sha256:9eef859907a3b96c873476eda6a31627c12d652f2584449c0f74b61df5c2181d`
- digest: `sha256:9eef859907a3b96c873476eda6a31627c12d652f2584449c0f74b61df5c2181d`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
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
