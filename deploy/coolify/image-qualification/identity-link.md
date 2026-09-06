# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:6dbc384b6d28687ef927c685983df22dc3624997e666ee3808d5466d2c82b916`
- digest: `sha256:6dbc384b6d28687ef927c685983df22dc3624997e666ee3808d5466d2c82b916`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34004823087`
- source commit `0a55001bf905d2441dee4580f9593643e1fa2236`
The image was built, published, and qualified by the referenced CI run.
