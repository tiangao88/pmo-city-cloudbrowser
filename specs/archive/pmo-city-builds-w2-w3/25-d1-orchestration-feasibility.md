# D1 Orchestration Feasibility (25)

> **Status:** S1+S2 COMPLETE (runtime mechanics) + **S6 COMPLETE — PASS
> 2026-08-19** (Coolify-native service creation verified end-to-end).
> Production mechanism confirmed: Coolify-managed compose via API.
> A1 decision input ready; S3 spawner prototype next.

## ⚠️ Review 2026-08-19 — production = Coolify-managed compose, no hacks

**Tigo's constraint:** production = a standard Coolify-hosted application
created with a **Coolify Docker Compose**. No direct traefik dynamic-config
rules pointing at local IPs/ports of applications not managed through
Coolify. Every instance must be **visible in Coolify**.

**Consequence for S1/S2 (mechanism, not conclusions):**

| Probe | Probe mechanism (dev-only) | Production mechanism (Coolify-native) |
|---|---|---|
| S1 spawn | raw `docker create/start` on host | **`POST /api/v1/services`** with parameterized compose (`docker_compose_raw` base64, `urls`, `instant_deploy`) — or `POST /services/{uuid}/clone` (A1 clone-per-user, API-native) |
| S2 route+TLS | hand-written dynamic file `cbprobe.yaml` | **Coolify `urls` / Domains tab** → standard label generation + LE TLS (exactly like the viewer today) |
| S2 gate | labels on raw container | labels in the per-user **compose** (`tinyauth.apps.<unique-key>.*`), applied by Coolify at deploy |

**What STANDS from S1/S2 (mechanism-independent):**
- A fresh instance boots the whole verified stack (shared scripts volume ro,
  CfT binary must be seeded into the profile volume, chown 1000:1000)
- tinyauth v5 gates late-spawned instances **per request** (live
  ContainerList+Inspect scan, source-proven) — the container origin
  (raw docker vs Coolify) is irrelevant to the gate
- Broker-assisted SSO works in a spawned instance (D15 Phase C synergy)

**Coolify API evidence (openapi.json, coollabsio/coolify):**
- `POST /services` — create: `docker_compose_raw`, `urls[]`,
  `instant_deploy`, `project_uuid`, `environment_name/uuid`, `server_uuid`,
  `destination_uuid`, `force_domain_override`
- `POST /services/{uuid}/clone` — clone with `name` + `clone_volumes`
- `POST /services/{uuid}/start|stop|restart`
- `POST /services/{uuid}/envs` (+`bulk`) — per-user env
- `DELETE /services/{uuid}`
⇒ the whole spawner lifecycle exists in the Coolify API.

**TOKEN RESOLVED 2026-08-19:** Tigo provided a root-scoped token (stored in
Vaultwarden `hermes_env_dev`). Diagnostics note: the earlier `403 not
allowed` was NOT token scope — it was a client-side misroute (curl
`--resolve` to the public IP instead of the docker-network `coolify-proxy`
IP → Coolify's IP allowlist rejected the source). Correct pattern (in
`coolify-api-operations` skill): resolve `coolify-proxy` at call time.

**Cleanup DONE 2026-08-19 (pre-S6, per Tigo):** `/data/coolify/proxy/dynamic/cbprobe.yaml`
removed (cbprobe → 404), `cb-probe-s1` container + volumes removed, live
services untouched.

---

## S6 VERDICT — PASS via CLONE (2026-08-19, Coolify API, PMO City / development)

**Two attempts, one verdict.** First attempt = hand-written compose
`cb-probe-s6` (`frmcsej8ju17v97lpvnsgd4c`, domain `s6probe.dev01.pmo.city`) —
**REJECTED by Tigo**: not using Coolify magic vars, mounting another app's
volume, not best practice → destroyed cleanly via API
(`delete_configurations=true&delete_volumes=true&docker_cleanup=true`,
verified no containers/volumes/network/domain leftovers).

**Second attempt = API-native clone of the cloudbrowser stack itself**
(never touching the live service): `POST /services/4guplgcrvug7l7h64m2cxkm1/clone`
→ **201** `{"uuid":"xuq0yey89m0zrqphf8e73hhr"}` → renamed per Tigo's convention
**`cb-probe-s6-xuq0yey89m0zrqphf8e73hhr`** (service name suffixed with service
ID). Inherited: project PMO City / development, destination `pmoc-lan`,
`connect_to_docker_network:true`, full env incl. FAKE_LOGIN_PASS, all 5
children (viewer/browser/clamav/janitor/fake-login), compose raw.

**Needed per-clone changes (all via API PATCH):**
- **tinyauth app-keys re-keyed** to the clone's uuid: `tinyauth.apps.xuq0yey89m0zrqphf8e73hhr-cloudbrowser.config.domain=cbclone.dev01.pmo.city` + `…-cloudfiles…=cbfiles.dev01.pmo.city` (docker-compose raw PATCH, base64)
- **domains with ports**: `urls: [{name: viewer, url: "https://cbclone.dev01.pmo.city:8081,https://cbfiles.dev01.pmo.city:9231"}]` — Coolify **regenerated the magic vars** (`SERVICE_URL_CLOUDBROWSER_8081` → `https://cbclone.dev01.pmo.city:8081`) from the PATCHed domains
- **EPR ports moved off the collision** — CRITICAL multi-instance finding: the compose maps host UDP `52000-52100`, already held by the live viewer → first boot: viewer created with **no network** (`NetworkSettings.Networks={}`), neko panic `failed to fetch ip address`. Fix: env `NEKO_EPR=52101-52201` + compose `ports: 52101-52201:52101-52201/udp`
- **SSL procedure (Tigo):** start first time → `POST /stop` with `docker_cleanup:true` → wait **fully stopped** (containers 5→0) → `POST /start` → LE certs issued on second boot (lego log 17:20:42–55, CN=cbclone + CN=cbfiles)

| Check | Result | Evidence |
|---|---|---|
| Clone via API | ✅ 201 | `POST /services/{uuid}/clone` → uuid `xuq0yey89m0zrqphf8e73hhr`, children + envs + magic vars inherited |
| Rename (ID suffix) | ✅ 200 | PATCH `name` → `cb-probe-s6-xuq0yey89m0zrqphf8e73hhr` |
| Volumes (fresh, own) | ✅ | 5 volumes `<uuid>_scripts/viewer-profiles/downloads/browser-profiles/clamav-db`; **survive stop/start**; seeded once from source data (scripts mirror 508K + cft-chrome-128 663M, chown 1000:1000) — no cross-app mounts in compose |
| Route live | ✅ | `https://cbclone.dev01.pmo.city/` → HTTP/2 401; `cbfiles` same |
| TLS | ✅ | LE certs CN=cbclone.dev01.pmo.city / CN=cbfiles.dev01.pmo.city (start-stop-start, lego log) |
| tinyauth gate | ✅ | `x-tinyauth-location: https://auth.pmo.city/login?login_for=app&redirect_uri=https%3A%2F%2Fcbclone.dev01.pmo.city%2F` (label provider live-lookup, no tinyauth restart) |
| Broker SSO E2E | ✅ | fresh Chrome via CDP `10.0.37.16:9223` → cbclone → broker autofill → session cookie `.pmo.city` → title **"Cloudbrowser: spike-user@aikumi.pro"**, neko UI loaded |
| Networks | ✅ | stack net `xuq0yey89m0zrqphf8e73hhr`=10.0.34.7 **+ pmoc-lan** `vb42gxxv4hlqwd96ct639lf2`=10.0.37.16 |
| Stack boot | ✅ | supervisord all RUNNING (neko/google-chrome/cdp-relay/sso-broker/downloads-api/title-proxy) |
| Stop/start round-trip | ✅ | stop `docker_cleanup` → containers 0 → start → full stack back, same volumes, no re-seed |

**Production-mechanism conclusions (feed A1):**
- **Clone-per-user (A1) is feasible on the Coolify-managed path, API-native.**
  The spawner recipe = clone (inherits envs+magic vars+children) → re-key
  tinyauth app-keys to the new uuid → PATCH domains (`urls`, ports included)
  → seed fresh volumes once (scripts + CfT binary) → start → stop→start for
  SSL. All steps proven live.
- **EPR port ranges are a per-host shared resource**: every instance on the
  same server needs its own UDP range (env `NEKO_EPR` + compose `ports` must
  move together). Source of the only first-boot failure.
- Fresh instances need the CfT binary seeded into the profile volume once
  (S1 finding; volumes persist across stop/start → seed per-create, not
  per-start).
- `connect_to_docker_network:true` must be set before first start (inherited
  by clone) for the pmoc-lan CDP route.
- Watchtower labels: omit on spawns (scope=monitor-notify watches labeled
  containers only; probe excluded).
- Naming: service name suffixed with service ID (Tigo convention, matches
  `cloudbrowser-4guplgcrvug7l7h64m2cxkm1`).

**Cleanup:** probe left RUNNING for Tigo's UI inspection; teardown = DELETE
`/services/xuq0yey89m0zrqphf8e73hhr` (delete_configurations + delete_volumes +
docker_cleanup), then remove `s6probe`/`cbclone`/`cbfiles` DNS entries if
wildcard not used.

---


A1 (per-user browsers, D1) can only choose **clone-per-user for the pilot**
if the **production target — orchestrator-spawned on-demand instances — is
technically feasible**. If not, cloud browser needs a different solution
altogether. So before A1: prove the target on dev.

## Target definition (what feasibility means)

Spawn a fresh neko/Chrome instance per user **on demand** → user SSOs into
*their* browser → uses it → idle-stop → respawn later → same profile, tabs,
downloads back. Fleet cap enforced (`MAX_RUNNING_BROWSERS`). No restart of
the viewer or traefik involved in spawn/stop.

---

## ✅ S1 — Dynamic instance spawn: PASS

Probe `cb-probe-s1` created from the same pinned image
(`ghcr.io/m1k1o/neko/google-chrome:2.9.0`, cached) on mother01:
- Fresh named volumes (profile + downloads), shared **scripts volume (ro)**
  → tabbar, branding, chrome.conf, sso-broker all inherited
- Attached to the same two networks as the viewer; IPs `10.0.38.8` /
  `10.0.37.12`; `--memory 2g` (D9 policy); no published ports (IP-routable)
- **Verified live:** supervisord all RUNNING (cdp-relay, downloads-api,
  google-chrome, neko, pulseaudio, restart-api, sso-broker, title-proxy,
  window-manager, x-server); neko HTTP 200 on :8080; CDP relay →
  `Chrome/128.0.6613.137` on :9223

### S1 findings (provisioning requirements for the spawner)

1. **CfT Chrome binary (663 MB) lives inside the profile volume**
   (`…/google-chrome-w1/cft-chrome-128/`), path baked into the shared
   `prepare-chrome.sh` (`exec "$PROFILE/cft-chrome-128/chrome"`). A fresh
   instance has **no Chrome binary** → google-chrome FATAL. Spawner must
   seed the binary (volume template or shared RO binary mount) or move the
   path to a shared location.
2. **Fresh volumes are root-owned** → must `chown -R 1000:1000` the profile
   + downloads dirs before Chrome starts (tooling-init runs too early to
   help as-is).
3. Shared scripts volume (ro) makes every instance byte-identical to the
   viewer stack — instances are cheap to spawn.

## ✅ S2 — Dynamic routing + tinyauth gate: PASS (make-or-break → GREEN)

### 2a. Route + TLS materialize automatically (no restart)
- Dynamic file `/data/coolify/proxy/dynamic/cbprobe.yaml` (traefik file
  provider, watched dir) → router `Host(cbprobe.dev01.pmo.city)` →
  `http://10.0.38.8:8080` + middleware `tinyauth-pmo@file` → **active on
  next request, zero restarts**
- **TLS auto-issued:** lego obtained a Let's Encrypt cert for
  `cbprobe.dev01.pmo.city` automatically (observed in traefik logs:
  "Obtaining bundled SAN certificate" → "Server responded with a
  certificate")
- Wildcard DNS `*.dev01.pmo.city` already resolves → no DNS work per domain
- ⚠️ **Atomicity:** one malformed YAML drops the WHOLE file (observed when
  a bad append killed the route until fixed). Spawner must write valid YAML
  + validate before write.

### 2b. tinyauth discovers late-spawned instances — source-proven
From tinyauth v5 source (github.com/tinyauthapp/tinyauth):
- `internal/controller/proxy_controller.go:105` — `GetAccessControls(host)`
  runs **on every auth request**
- `internal/service/access_controls_service.go:100-116` — static config
  first, then label provider `Lookup`
- `internal/service/docker_service.go:70-100` — `Lookup` does a **live
  `ContainerList` + `ContainerInspect` scan of ALL containers on every
  call**; `watchAndClose` only handles context cancel — no event cache
- Domain match = exact `config.domain` (proven semantics from the label-fix
  investigation; group enforcement proven live 2026-08-18 with the
  nico.verdi denial)

⇒ **A container spawned AFTER tinyauth started, carrying
`tinyauth.apps.<name>.config.domain` + `.oauth.groups` labels, is gated on
its very next request. No restart, no watcher, no cache.**

### 2c. Live E2E (probe Chrome)
1. Unauth `GET https://cbprobe.dev01.pmo.city/` → `401` +
   `X-Tinyauth-Location: https://auth.pmo.city/login?login_for=app…`
2. Probe's own Chrome opened the URL → tinyauth → Authentik login →
   **sso-broker auto-filled (spike-user)** → back to cbprobe
3. Session cookie `tinyauth-session-39fcd0f6` on `.pmo.city` (secure) issued
4. Authorized request with cookie → **HTTP/2 200** on the spawned instance
5. Screenshot `/opt/data/s2-e2e-probe.png`: Cloudbrowser-branded neko UI
   with tabbar on the probe (neko password gate = second gate, as designed)

⇒ **D15 Phase C synergy confirmed:** the broker boots and works in a
spawned instance (shared scripts volume carries `sso-broker.py` +
`sso-creds.b64`).

---

## Verdict

**The production target (orchestrator-spawned on-demand instances) is
technically feasible.** Every link of the chain is dynamic:
spawn (S1) → route + TLS (S2a) → gate (S2b) → login (S2c). No restart of
viewer/traefik/tinyauth anywhere.

## Remaining risks / S3-S4 scope

| Risk | Where | Mitigation |
|---|---|---|
| CfT binary per fresh profile | S1 finding 1 | seed step or shared RO mount |
| chown on fresh volumes | S1 finding 2 | spawner provision step |
| Route-file atomicity | S2a | validate-before-write in spawner |
| neko EPR port pools (52000-52100 per instance) | S4 | measure 3-4 concurrent; production may need per-instance EPR ranges/ICE strategy |
| Tab snapshot lives in-container (D5) | S3 | move snapshot to profile volume |
| Fleet cap enforcement | S3 | spawner checks MAX_RUNNING_BROWSERS before spawn |
| Coolify vs dynamic-file conflict | S2 | UI-managed domains coexist; spawner uses dynamic file only |

## State after S1+S2

- Probe `cb-probe-s1` left RUNNING (needed for S3), volumes
  `cb-probe-s1-profiles` / `cb-probe-s1-downloads`
- `/data/coolify/proxy/dynamic/cbprobe.yaml` in place (http+https routes)
- `cbprobe.dev01.pmo.city` has a live LE cert; broker login verified
- Teardown on request (Tigo) or after S3/S4
