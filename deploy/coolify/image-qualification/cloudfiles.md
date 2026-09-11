# Image qualification — cloudfiles

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/cloudfiles@sha256:d4231ad2bf4cc0c7e3c1a2e94197b4e6784ffdd0ff1cd9d1a5aafbbaa2d8092a`
- digest: `sha256:d4231ad2bf4cc0c7e3c1a2e94197b4e6784ffdd0ff1cd9d1a5aafbbaa2d8092a`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/cloudfiles/Dockerfile`
- runtime port: `8085`
- configured user: `cloudbrowser`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- source commit `8e455b4efbbde723c26c47879da1b339ca3835b5`
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34603628801`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `8e455b4efbbde723c26c47879da1b339ca3835b5` in CI run
`34603628801`, after every matrix job completed successfully. The CI job
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and the service health endpoint. No credentials,
cookies, tokens, passwords, or OTPs are included in this record.
