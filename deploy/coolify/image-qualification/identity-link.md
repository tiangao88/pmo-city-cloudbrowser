# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:20d0dbf7bf3855c03e496af7efc13cdf35d6e805604b9ee531e1870e5f02c011`
- digest: `sha256:20d0dbf7bf3855c03e496af7efc13cdf35d6e805604b9ee531e1870e5f02c011`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33933615971`
- source commit `5b38ec3138dea52dbcbc9fb69f793f06f449636c`
The image was built, published, and qualified by the referenced CI run.
