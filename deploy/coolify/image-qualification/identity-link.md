# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:0800251a6c2e469ae1b5924ffbe0a3ec64fd2942c7be38dbb9c924108a8e17b4`
- digest: `sha256:0800251a6c2e469ae1b5924ffbe0a3ec64fd2942c7be38dbb9c924108a8e17b4`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34231460028`
- source commit `949faea701cfc36a24f8f53713aac1693c9cd5eb`
The image was built, published, and qualified by the referenced CI run.
