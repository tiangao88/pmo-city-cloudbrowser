# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:a71976930ad0024f11a85d653a0fd1f5334291e875334314c2acd32728403cde`
- digest: `sha256:a71976930ad0024f11a85d653a0fd1f5334291e875334314c2acd32728403cde`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34172074303`
- source commit `f313fc3259e04b1854fa9b6ebed5bc6803b48289`
The image was built, published, and qualified by the referenced CI run.
