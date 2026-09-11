# Image qualification — viewer

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/viewer@sha256:3113045a3874acbcd4b2f1d35e579a2317b6485eb807ca5faed7326bef560538`
- digest: `sha256:3113045a3874acbcd4b2f1d35e579a2317b6485eb807ca5faed7326bef560538`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/viewer/Dockerfile`
- runtime port: `8082`
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
