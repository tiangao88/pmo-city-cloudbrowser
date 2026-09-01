# Full compose scaffold

The primary `deploy/coolify/compose.yaml` remains the release's five-service
scaffold. It intentionally does not include a browser process until the
installable release gates are approved. Each installation is isolated by
`CB_INSTANCE_ID`, including its network, volumes, and secret namespaces. For
local development of the restricted browser-side adapter, combine it with
`browser-overlay.yaml` using Compose's multiple-file merge behavior:

```bash
CB_INSTANCE_ID=cloudbrowser-dev-v01 \
CB_RELEASE_VERSION=0.2.0-dev1 \
docker compose -f deploy/coolify/compose.yaml \
  -f deploy/coolify/browser-overlay.yaml config
```

The overlay is not an installability or production-deployment approval.
