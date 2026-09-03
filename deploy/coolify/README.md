# Deploy compose (dev staging)

The primary `deploy/coolify/compose.yaml` defines the runtime services with
source-build contexts for local validation. The current compose includes the
internal `downloads` service; the planned public `cloudfiles` gateway is not
yet a deployable service. Each installation is isolated by `CB_INSTANCE_ID`,
including its network, volumes, and secret namespaces:

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

The downloads service is fronted at `cloudfiles2.dev01.pmo.city` as a second
Domains entry on the existing `cloudbrowser2` Coolify service. This follows the
same service-scoped model used by the live `cb-fleet` resource for its browser
and files hosts. No standalone `cloudfiles2` Coolify application is created.

The frozen product target adds an application-level CloudFiles gateway in front
of this internal service. The public host must target that gateway, which is
TinyAuth-protected at the edge and forwards a server-derived owner binding to
the downloads service. The downloads container must not be exposed directly as
the public product surface.

Coolify's Domains configuration generates the HTTP/HTTPS router and applies
the existing `tinyauth-pmo@file` middleware. Do not add compose-authored
Traefik routers for these public hosts: defining the route in both Compose and
Coolify generates duplicate routers for the same host rule.

### TinyAuth labels

`cloudbrowser2` uses explicit, stable TinyAuth app keys on the two exposed
containers. These keys are intentionally not raw deployment/container UUIDs;
the live `cb-fleet` resource uses the same short-key convention (`cloudbrowser`
and `cloudfiles`).

```yaml
# viewer application labels
- tinyauth.apps.cloudbrowser2-viewer.oauth.groups=PMOC_Users
- tinyauth.apps.cloudbrowser2-viewer.config.domain=cloudbrowser2.dev01.pmo.city
- traefik.http.middlewares.tinyauth-pmo@file

# downloads application labels
- tinyauth.apps.cloudbrowser2-downloads.oauth.groups=PMOC_Users
- tinyauth.apps.cloudbrowser2-downloads.config.domain=cloudfiles2.dev01.pmo.city
- traefik.http.middlewares.tinyauth-pmo@file
```

For reference, these are the live `cb-fleet` labels:

```yaml
- tinyauth.apps.cloudbrowser.config.domain=cloudbrowser.dev01.pmo.city
- tinyauth.apps.cloudbrowser.oauth.groups=PMOC_Users
- tinyauth.apps.cloudfiles.config.domain=cloudfiles.dev01.pmo.city
- tinyauth.apps.cloudfiles.oauth.groups=PMOC_Users
- traefik.http.middlewares.tinyauth-pmo@file
```

`oauth.groups=PMOC_Users` is the group authorization gate. `config.domain`
binds the TinyAuth app registration to the host. TinyAuth's Docker label
provider discovers these app keys from application containers; they are not
placed on the TinyAuth container. Coolify's Domains configuration provides the
actual HTTP/HTTPS router and attaches `tinyauth-pmo@file`. The route must not
also be authored in Compose.

`/health` remains unauthenticated for container healthchecks. Protected
file/API requests still require the downloads service's trusted secret and
server-derived owner headers after the edge authentication check.

The `browser-overlay.yaml` was folded into the main compose when the browser
service was added (step 11) and is retained only as a historical reference.

The dev staging service on Coolify is deployed for Step 19 runtime
qualification. The release manifest is `installable: true` because the Step-17
image qualification passed and the release images are pinned by immutable
digest. Remaining Step 19 acceptance gates are recorded in the runtime
qualification document.
