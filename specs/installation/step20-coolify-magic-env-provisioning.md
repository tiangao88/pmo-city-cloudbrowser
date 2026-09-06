# Step 20 — Coolify Magic-Env Self-Provisioning (v0.2.0-dev1)

Status: qualified (image digests unchanged — no rebuild/re-qualification required)

## Contract

`deploy/coolify/compose.coolify.yaml` is now fully self-provisioning for a
fresh Coolify service deploy (zero manual env setup):

- **Secrets** use Coolify magic env variables (`SERVICE_PASSWORD_64_<ID>`):
  Coolify auto-creates each one with a random 64-character alphanumeric value
  on first compose parse and keeps the value stable across redeploys; values
  are editable in the service Env tab. All six secrets use `PASSWORD_64`
  (URL-safe alphanumerics, safe in HTTP headers):

  | Secret                        | Magic var                                   |
  |-------------------------------|---------------------------------------------|
  | `CB_ROUTER_SHARED_SECRET`     | `${SERVICE_PASSWORD_64_ROUTERSECRET}`       |
  | `CB_AGENT_CONTROL_SHARED_SECRET` | `${SERVICE_PASSWORD_64_AGENTCTRLSECRET}` |
  | `CB_IDENTITY_LINK_SHARED_SECRET` | `${SERVICE_PASSWORD_64_IDLINKSECRET}`   |
  | `CB_DOWNLOADS_SHARED_SECRET`  | `${SERVICE_PASSWORD_64_DLSECRET}`           |
  | `CB_DOWNLOADS_INGEST_SECRET`  | `${SERVICE_PASSWORD_64_INGESTSECRET}`       |
  | `CB_VIEWER_TOKEN_SECRET`      | `${SERVICE_PASSWORD_64_VIEWERSECRET}`       |

  Identifier rules (from Coolify's `parseEnvVariable`): identifiers must not
  contain underscores (they would shift the `beforeLast('_')` command split);
  hyphens are allowed but the fleet convention is underscore-free uppercase.

- **Configuration** carries deploy-safe `${CB_X:-default}` defaults matching
  dev01 (instance id, release version, edge auth, OIDC issuer, TinyAuth realm,
  supervisor/agent-control URL maps, binding ids, generation).

- The source-build variant `deploy/coolify/compose.yaml` keeps the
  `${CB_X:?...}` fail-closed contract unchanged.

## Rotation semantics

Every secret is consumed only by services inside this single Coolify service,
so switching to magic envs rotates them once at redeploy with no external
sync needed. Viewer token sessions reset (clients re-authenticate via SSO).

## Tests

- `tests/installation/test_installation_validator.py` /
  `tools/validate-installation.py` assert all six magic markers.
- `tests/installation/test_router_compose_wiring.py`,
  `tests/installation/test_downloads_installation.py`,
  `tests/installation/test_step18_installable_manifest.py`,
  `tests/contract/test_ingest_deployment_wiring.py` carry per-variant
  expectations (source-build: `:?required`; Coolify: magic/defaults).
- The router "not a public host" guard now asserts absence of
  `traefik.http` router keys / `tinyauth.apps` labels instead of the
  substrings, because the Coolify variant legitimately carries
  `traefik-forwardauth` / `tinyauth-pmo` as env values.
