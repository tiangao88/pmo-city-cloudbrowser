# Standalone desktop qualification stack

This is **not** a Coolify override or a dev01 deployment. It uses a new Compose
project and new state volumes. Do not combine it with either release Compose
file, point it at production volumes, or copy the authentication fixture into a
deployment. Credentials are disabled at both desktop and router, and there is
no broker service or Vaultwarden configuration.

The topology is Traefik → desktop/router → supervisor/agent-control/browser,
with a real private identity-link service. Only Traefik is published, bound to
127.0.0.1. It uses file configuration, not a mounted Docker socket. Both public
host routes require forward-auth. `authResponseHeadersRegex` strips matching
caller headers before copying identity headers from the authentication response,
as specified by [Traefik ForwardAuth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/forwardauth/).
Compose's inline `configs.content` requires a supporting Compose version;
[Docker documents the feature here](https://docs.docker.com/reference/compose-file/configs/).

## Synthetic local run

Use a fresh project name, a temporary self-signed certificate covering
`desktop.example.test` and `router.example.test`, and the intentionally public
synthetic values in `experiments/novnc/qualification.env`. Export only these
task-specific settings before starting:

```sh
export CB_DESKTOP_PROJECT=cb-desktop-qual-mytest
export CB_DESKTOP_TLS_CERT=/absolute/temporary/path/cert.pem
export CB_DESKTOP_TLS_KEY=/absolute/temporary/path/key.pem
docker compose --env-file experiments/novnc/qualification.env \
  -f deploy/desktop/compose.candidate.yaml \
  -f experiments/novnc/compose.auth-fixture.yaml up -d --build --wait
.venv/bin/python experiments/novnc/stack_smoke.py
```

The test connects only to 127.0.0.1:18443, setting Host headers for the two fixture
names; no hosts-file or DNS changes are needed. Its certificate-verification
exception applies only to this localhost test client. The synthetic
`fixture_user` cookie is not authentication and must never be accepted outside
the disposable fixture. The test never prints viewer cookies or uses real accounts.

After testing, stop the same explicitly named project with the same env/file
arguments and `down`. Add `--volumes` **only for a freshly created disposable
qualification project**: that permanently deletes its synthetic profile/session
data. Never run this against an existing user-data project.

## Actual authentication configuration (not yet qualified)

Omit `compose.auth-fixture.yaml` and `qualification.env`. Supply distinct secrets,
the actual issuer/realm, an authenticated HTTPS forward-auth endpoint, reviewed
Traefik image, certificate/key paths, and two distinct host names. Set
`CB_VIEWER_PUBLIC_ORIGIN` to the exact browser-visible HTTPS origin, including a
non-default port when applicable. The current stack intentionally stays bound
to localhost; exposing it requires a separate reviewed deployment change.

The successful synthetic run validates service wiring, not real SSO, ongoing
SSO revocation, credential custody, a leader-election protocol or release
readiness. The blocked security review and release gates still apply.
