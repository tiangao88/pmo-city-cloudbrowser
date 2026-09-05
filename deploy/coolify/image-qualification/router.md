# Image qualification — router

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/router@sha256:f645de79032de86c3c5a0f8ae452a8af671da8f13bf4a7977027e1616c85cefc`
- digest: `sha256:f645de79032de86c3c5a0f8ae452a8af671da8f13bf4a7977027e1616c85cefc`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/router/Dockerfile`
- runtime port: `8080`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33931242688`
- source commit `7ce73abbb3b3e4c7275bc2caf9adc55ba7894de6`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built
from source commit `7ce73abbb3b3e4c7275bc2caf9adc55ba7894de6` in CI run `33931242688`, after every matrix job
completed successfully. The CI job verified the non-root user, image
healthcheck, provenance/SBOM metadata, container health, runtime UID, and the
service health endpoint. No credentials, cookies, tokens, passwords, or OTPs
are included in this record.
