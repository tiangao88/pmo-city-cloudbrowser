# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router@sha256:24b97edeb3a5aa9dde3fa184ec34ffa92742a3a599984612a8a48b942e99d234`
- digest: `sha256:24b97edeb3a5aa9dde3fa184ec34ffa92742a3a599984612a8a48b942e99d234`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `2e300efc359d8b5706d8b84a30058fa99e9e01f9`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34623825124`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `2e300efc359d8b5706d8b84a30058fa99e9e01f9` in CI run
`34623825124`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
