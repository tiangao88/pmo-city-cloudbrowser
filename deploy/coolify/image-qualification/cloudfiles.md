# Image qualification — cloudfiles

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/cloudfiles@sha256:9448204a5554148aa19da3f17f4584e011d390c1b7c8ed7c4bb774546cfdca52`
- digest: `sha256:9448204a5554148aa19da3f17f4584e011d390c1b7c8ed7c4bb774546cfdca52`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/cloudfiles/Dockerfile`
- runtime port: `8085`
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
