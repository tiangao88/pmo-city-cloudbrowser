# Deploy compose (dev staging)

The primary `deploy/coolify/compose.yaml` defines the runtime services with
source-build contexts for local validation. It includes the internal
`downloads` service and the TinyAuth-protected public `cloudfiles` gateway.
Each installation is isolated by `CB_INSTANCE_ID`, including its network,
volumes, and secret namespaces.

Copy `deploy/coolify/.env.example` to an untracked
`deploy/coolify/.env`, replace every secret placeholder from an approved secret
manager, and review all site/identity values before rendering:

```bash
docker compose --env-file deploy/coolify/.env \
  -f deploy/coolify/compose.yaml config
```

The two-variable shorthand is intentionally not supported: source Compose
requires the control-plane secrets, custody KEK, Vault URL, site declaration,
and identity/binding inputs documented in `.env.example`.

For Coolify deployment, `compose.coolify.yaml` is the image-based variant.
Coolify API-created compose services cannot clone the private repository to
satisfy `build:` contexts, so this variant uses immutable image digests and
keeps the same environment, healthcheck, volume, and network wiring. The
current digests qualify commit `ce0ef5d` in CI run `34594208145`; the release
manifest and qualification records are synchronized to those immutable pins.

## Public CloudFiles host

The `cloudfiles` gateway is the only service eligible to receive
`cloudfiles2.dev01.pmo.city` as a second Domains entry on the existing
`cloudbrowser2` Coolify service. This follows the same service-scoped model
used by the live `cb-fleet` resource for its browser and files hosts. No
standalone `cloudfiles2` Coolify application is created. The internal
`downloads` service must never be exposed directly.

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

# cloudfiles application labels
- tinyauth.apps.cloudbrowser2-cloudfiles.oauth.groups=PMOC_Users
- tinyauth.apps.cloudbrowser2-cloudfiles.config.domain=cloudfiles2.dev01.pmo.city
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
file/API requests reach CloudFiles only after edge authentication; CloudFiles
maps the TinyAuth session to a server-derived immutable owner and uses the
private downloads-service secret. The browser client never supplies owner
headers or accesses `downloads` directly.

The `browser-overlay.yaml` was folded into the main compose when the browser
service was added (step 11) and is retained only as a historical reference.

The dev staging service on Coolify remains the Step 19 runtime-qualification
target. The release manifest is installable: its nine immutable image digests
and qualification records describe source commit `ce0ef5d`, built and qualified
in CI run `34594208145`. Deployment and runtime/security acceptance remain
separate recorded outcomes.
