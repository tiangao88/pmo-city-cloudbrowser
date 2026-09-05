# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:4c393fa4e10f9e5dd55918d55e3f51407c1b141bb70d7dbaa79c4ecfa4cee727`
- digest: `sha256:4c393fa4e10f9e5dd55918d55e3f51407c1b141bb70d7dbaa79c4ecfa4cee727`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33933030083`
- source commit `20cadd59e3ded2d1e6783573d948f368a9846a9f`

The image was built, published, and qualified by the referenced CI run.
