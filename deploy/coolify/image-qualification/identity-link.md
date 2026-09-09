# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:0bc96f0a6d21156c14779182f4cb4e0a625bf413aaa710c93dc8fd3eb2e7294b`
- digest: `sha256:0bc96f0a6d21156c14779182f4cb4e0a625bf413aaa710c93dc8fd3eb2e7294b`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34402569940`
- source commit `50ce1984448ddf79621d4114f81c6a2b2b83d5fa`
The image was built, published, and qualified by the referenced CI run.
