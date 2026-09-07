# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:834fe2d875e1f7cad6af4efcc00e6d0a550c22eed1f15463166be936f055b795`
- digest: `sha256:834fe2d875e1f7cad6af4efcc00e6d0a550c22eed1f15463166be936f055b795`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34086579113`
- source commit `40fb03d2025f37eb471ed12e5deb0f24d2469277`
The image was built, published, and qualified by the referenced CI run.
