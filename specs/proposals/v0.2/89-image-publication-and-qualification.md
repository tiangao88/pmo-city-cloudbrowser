# CloudBrowser image publication and qualification

Step 17 prepares the runtime images for CI publication; it does not make the
current broker milestone installable and does not deploy anything to Coolify.

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
`deploy/coolify/image-qualification/<service>.md`. These are evidence records,
not a declaration that an image is installable or that the Credential Broker's
login capabilities are live-qualified.

The v0.2.0-dev1 pins are stale relative to the current source/spec checkpoint.
Do not edit them now. The release sequence is:

1. commit the source and specs;
2. have the user/operator trigger the GitHub Actions build from that source
   commit because current token limits prevent an automatic trigger;
3. verify CI provenance/SBOM and synchronize digests in a separate release
   change;
4. run the provenance/full gates against the synchronized pins;
5. obtain separate approval for deployment and live/closed-shadow qualification.

Docker image builds cannot be exercised locally here because the local Docker
daemon is unavailable; CI is the build authority.
