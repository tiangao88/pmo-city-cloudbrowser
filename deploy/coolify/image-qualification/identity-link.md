# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:fc47429540c2242193e661056585582ec4d80d92d90cf166ca57696eb184013d`
- digest: `sha256:fc47429540c2242193e661056585582ec4d80d92d90cf166ca57696eb184013d`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34219815337`
- source commit `2c6a6e7702069b9d918585768770169c9896ccb6`
The image was built, published, and qualified by the referenced CI run.
