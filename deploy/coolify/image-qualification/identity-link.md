# Image qualification — identity-link

- image: `ghcr.io/tiangao88/pmo-city-cloudbrowser/identity-link@sha256:f1c632b8a38b8155f08409fc6078cb38d48caf17b2177e3550064a0c525f7b57`
- digest: `sha256:f1c632b8a38b8155f08409fc6078cb38d48caf17b2177e3550064a0c525f7b57`
- status: passed
- build workflow: `.github/workflows/build-images.yml`
- Dockerfile: `services/identity-link/Dockerfile`
- runtime port: `8091`
- non-root: passed (`cloudbrowser`, uid 10001)
- healthcheck: passed (container status: healthy)
- configured user: `cloudbrowser`
- runtime endpoint: passed (`/health`)
- provenance/SBOM metadata: present in registry manifest
- CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/34173065983`
- source commit `241667324e901b2c027c97022d764b4bea778afc`
The image was built, published, and qualified by the referenced CI run.
