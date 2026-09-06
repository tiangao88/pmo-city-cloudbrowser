# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:8d11df117c421868a0f4ca86e25c2a95d16bde4c62c129d34cbbc26fb5a3a017`
- digest: `sha256:8d11df117c421868a0f4ca86e25c2a95d16bde4c62c129d34cbbc26fb5a3a017`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34061193670`
- source commit `164a2bf228821b7e0c042aa904c55bec73b521ab`
The image was built, published, and qualified by the referenced CI run.
