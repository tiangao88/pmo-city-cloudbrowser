# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:f95785b99ff8dc78b6e79b7b7dd5c3f7f3e2b6c348c6fff70a3f2bd08accbb9b`
- digest: `sha256:f95785b99ff8dc78b6e79b7b7dd5c3f7f3e2b6c348c6fff70a3f2bd08accbb9b`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34067144442`
- source commit `40c1faa118b9b6af28aad7171040bae5c4ea27a2`
The image was built, published, and qualified by the referenced CI run.
