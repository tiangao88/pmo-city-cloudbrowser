# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:4a39a96f2325896d37cbe9731ffee43ef09f9de4ac129b30200d204857cb3eea`
- digest: `sha256:4a39a96f2325896d37cbe9731ffee43ef09f9de4ac129b30200d204857cb3eea`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34069562058`
- source commit `00836a3fe573149f4a294635e56847e7b2788bcc`
The image was built, published, and qualified by the referenced CI run.
