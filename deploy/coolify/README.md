# Deploy compose (dev staging)

The primary `deploy/coolify/compose.yaml` defines the six runtime services
(router, slot-supervisor, browser, viewer, downloads, credential-broker) with
source-build contexts for local validation. Each installation is isolated by
`CB_INSTANCE_ID`, including its network, volumes, and secret namespaces:

```bash
CB_INSTANCE_ID=cloudbrowser-dev-v01 \
CB_RELEASE_VERSION=0.2.0-dev1 \
docker compose -f deploy/coolify/compose.yaml config
```

For Coolify deployment, `compose.coolify.yaml` is the image-based variant:
Coolify API-created compose services cannot clone the private repository to
satisfy `build:` contexts, so the deployed compose pins the published dev
images (`ghcr.io/tiangao88/pmo-city-cloudbrowser/<service>:v0.2.0-dev1`) and
keeps the same environment, healthcheck, volume, and network wiring.

## Public downloads host

The downloads service is fronted at `cloudfiles2.dev01.pmo.city`
(`CB_PUBLIC_FILES_HOST` in `.env.example`). The Traefik router for that host
is **not** embedded inside this compose: it is created in step 19 against
the standalone `cloudfiles2` Coolify application so that the downloads
surface is independently reachable from the CloudBrowser control plane.

The `browser-overlay.yaml` was folded into the main compose when the browser
service was added (step 11) and is retained only as a historical reference.

The dev staging service on Coolify is **not** a production release: the
release manifest remains `installable: false` until image digests are pinned
and the runtime/security acceptance matrix is approved.
