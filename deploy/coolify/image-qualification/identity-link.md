# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:REPLACE_BEFORE_IMAGE_PUBLICATION`
- digest: `sha256:REPLACE_BEFORE_IMAGE_PUBLICATION`
- status: pending
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: pending (requires published image)
- configured user: `cloudbrowser`
- runtime endpoint: pending (requires published image)
- provenance/SBOM metadata: pending registry publication
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33827177104`
- source commit `1d9ea90750d6ee4a3e39071fd14650891f06115e`

This record is a qualification placeholder. Replace the digest and evidence
with the actual CI-published image result before treating the release as
installable.
