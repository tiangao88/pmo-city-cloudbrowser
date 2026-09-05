# Image qualification — credential-broker

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/credential-broker@sha256:b4b18c597d34b162b9f91a685e6bafab41c080ef18e29d73e6bdcd2af8ed3f34`
- digest: `sha256:b4b18c597d34b162b9f91a685e6bafab41c080ef18e29d73e6bdcd2af8ed3f34`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/credential-broker/Dockerfile`
- runtime port: `8084`
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
