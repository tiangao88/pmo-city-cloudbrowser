# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router@sha256:f2e7ec3c3a4e9330eaf6f1c53da557e5d9a24f16793ad5e64e5aee370c56b9fb`
- digest: `sha256:f2e7ec3c3a4e9330eaf6f1c53da557e5d9a24f16793ad5e64e5aee370c56b9fb`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33827177104`
- source commit `1d9ea90750d6ee4a3e39071fd14650891f06115e`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `1d9ea90750d6ee4a3e39071fd14650891f06115e` in CI run `33933615971`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
