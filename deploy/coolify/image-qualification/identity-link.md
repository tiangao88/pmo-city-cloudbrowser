# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:26864de0d28f0de8d0ab920456326a1dc2be35fb3f365c8fdc7edd601ad8b400`
- digest: `sha256:26864de0d28f0de8d0ab920456326a1dc2be35fb3f365c8fdc7edd601ad8b400`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34121163838`
- source commit `d1ca5cf5e5b67e44baf25e1a4e8d34a3a4cdfb15`
The image was built, published, and qualified by the referenced CI run.
