# Image qualification — downloads

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/downloads:v0.2.0-dev1`
- digest: `sha256:04516af52481aa4f616458a073d90548a7267f1df277eee45e94b2286651f201`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/downloads/Dockerfile`
- runtime port: `8083`
- public host: `cloudfiles2.dev01.pmo.city` (route is step 19)
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
container health, runtime UID, and downloads health endpoint. The durable
volume is configured by the Coolify compose. No credentials, cookies, tokens,
passwords, or OTPs are included in this record.
