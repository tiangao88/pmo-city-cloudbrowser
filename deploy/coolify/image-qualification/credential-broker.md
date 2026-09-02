# Image qualification — credential-broker

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/credential-broker:v0.2.0-dev1`
- digest: `sha256:6b43206713d27c41a00a9a5228b15e57e1d99586805d5e1215a2dd38946745e9`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/credential-broker/Dockerfile`
- runtime port: `8084`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (`GET /health`; container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33684797404`
- source commit `d640b56fb66fe49f2d944c21cbdd4fc88b681b42`

## Qualification evidence

The immutable digest was resolved from the GHCR manifest for the image built from
source commit `d640b56fb66fe49f2d944c21cbdd4fc88b681b42` in CI run
`33684797404`, after every matrix job completed successfully. The CI job also
verified the non-root user, image healthcheck, provenance/SBOM metadata,
container health, runtime UID, and status-only broker health endpoint. No live
credential operation was performed as part of this qualification. No
credentials, cookies, tokens, passwords, or OTPs are included in this record.
