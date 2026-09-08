# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:ded11ba97141d09208b2425d2b3d38a99f10fb905f1b5caf78056946b00f58aa`
- digest: `sha256:ded11ba97141d09208b2425d2b3d38a99f10fb905f1b5caf78056946b00f58aa`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34208689175`
- source commit `1942f121c969285ad5dafa5ba0188c5fdf471fa9`
The image was built, published, and qualified by the referenced CI run.
