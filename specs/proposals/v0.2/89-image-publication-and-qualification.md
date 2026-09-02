# CloudBrowser image publication and qualification

Step 17 prepares the seven runtime images for CI publication; it does not
make the release installable and does not deploy anything to Coolify.

## Build trigger

`.github/workflows/build-images.yml` runs `uv run make check` in a separate
`validate` job. Only if that job succeeds does the `build` job publish the
complete matrix to GHCR:

- `router`
- `slot-supervisor`
- `browser`
- `viewer`
- `agent-control`
- `downloads`
- `credential-broker`

The build uses BuildKit provenance and SBOM attestations. Manual dispatch is
available for a controlled qualification run; tag pushes matching
`v0.2.0-dev*` publish images with both the release tag and commit tag.

## Qualification gate

After CI publishes images, record the immutable digest, non-root runtime user,
healthcheck result, startup result, and provenance/SBOM evidence in
`deploy/coolify/image-qualification/<service>.md`. These are evidence
records, not a declaration that an image is installable.

The v0.2.0-dev1 manifest continues to use
`sha256:REPLACE_BEFORE_IMAGE_PUBLICATION` and `installable: false` until the
seven image records and the runtime/security acceptance matrix are complete.
Docker image builds cannot be exercised locally here because the local Docker
daemon is unavailable; CI is the build authority.
