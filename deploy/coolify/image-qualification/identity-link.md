# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:63f6718d0dcf3ab41251315f7143b26deadc089844c912497a2fc6ed8d6bc59d`
- digest: `sha256:63f6718d0dcf3ab41251315f7143b26deadc089844c912497a2fc6ed8d6bc59d`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34043783268`
- source commit `ad61d9ee2899771c24dda4c4d7cb2438c6445e56`
The image was built, published, and qualified by the referenced CI run.
