# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:037e2a44c59b570a72424e456d77530115dafdaeeeffc5456713b2bdaebcc823`
- digest: `sha256:037e2a44c59b570a72424e456d77530115dafdaeeeffc5456713b2bdaebcc823`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34594208145`
- source commit `ce0ef5df54eda344692d17498cbbb297fe2161fb`
The image was built, published, and qualified by the referenced CI run.
