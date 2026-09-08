# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:49bb718f6ffda0d5ea43020bb2c00509b5b70edf7dcdd0713ec0bd6ce6fcfc0a`
- digest: `sha256:49bb718f6ffda0d5ea43020bb2c00509b5b70edf7dcdd0713ec0bd6ce6fcfc0a`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34246186158`
- source commit `fd3985ba0d247f17139a484fa8e6e3a0aa6f1226`
The image was built, published, and qualified by the referenced CI run.
