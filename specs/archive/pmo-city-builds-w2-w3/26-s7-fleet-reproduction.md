# S7 Fleet v2 — Reproduction & Sync Runbook

**Status: 2026-08-20 — every file below was sha-verified against the live
deployments (W2 fleet on dev01, W1 viewer) on this date.** This is the
single source of truth for rebuilding both stacks from zero.

W2 builds on W1: same neko image, same scripts-volume pattern, same
CDP/CfT decisions. The W1 viewer is the reference implementation and stays
running (demo, broker, CfT binary source).

---

## 1. The two Coolify stacks (prod server_id 0, mother01)

| Stack | UUID | Compose (repo mirror) | Containers |
|---|---|---|---|
| W1 viewer | `4guplgcrvug7l7h64m2cxkm1` | `specs/26-s7-viewer-compose.yaml` | viewer (neko), janitor, clamav, browser (legacy zenika), fake-login (legacy) |
| W2 fleet | `okixw2fxnwn1lakxvxajodww` | `specs/26-s7-fleet-compose-v2.yaml` | router, slot-1, slot-2, janitor, clamav |

Coolify stores the compose **rendered**; the repo mirrors the **authored
raw** (`KEY=VALUE`, `${VAR:-default}`). Rules: PATCH `docker_compose_raw`
base64-only; NEVER write a rendered compose back; domain adds are a UI-tab
operation; per-service env overrides live in the UI.

Image pins:
- neko: `ghcr.io/m1k1o/neko/google-chrome:2.9.0`
- router/janitor: `python:3.12-slim`
- clamav: `clamav/clamav:stable`
- (viewer legacy only) browser: `zenika/alpine-chrome:latest`

Domains (tinyauth forwardAuth, groups=PMOC_Users, domain labels in
compose): `s7fleet.dev01.pmo.city` (fleet), `cloudbrowser.dev01.pmo.city` +
`cloudfiles.dev01.pmo.city` (viewer).

### Agent path — direct CDP over pmoc-lan (NO ssh tunnel) — 2026-08-21

The agent drives the slot's Chrome over plain HTTP + WebSocket on the
pmoc-lan mesh. Per-slot TCP publishes (on `0.0.0.0` — no hardcoded IP,
so the mapping survives docker network recreation):

| Service | Host port | Container port | Purpose |
|---|---|---|---|
| slot-1 CDP relay | `9223` | `9223` | Chrome DevTools (relay → `127.0.0.1:9222`) |
| slot-1 restart-api | `9230` | `9230` | `GET /health`, `POST /restart` |
| slot-2 CDP relay | `9224` | `9223` | slot-2 CDP (offset +1) |
| slot-2 restart-api | `9231` | `9230` | slot-2 restart-api |

**Access control = host firewall, not an IP-bound publish** (an IP-bound
publish like `10.0.5.1:9223` breaks when docker recreates the bridge
network). Rules live in the `DOCKER-USER` chain (checked before docker's
own FORWARD rules), keyed to the stable pmoc-lan subnet `10.0.0.0/8`:

```sh
iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -I DOCKER-USER 2 -p tcp -m multiport --dports 9223,9224,9230,9231 \
  -s 10.0.0.0/8 -j ACCEPT
iptables -I DOCKER-USER 3 -p tcp -m multiport --dports 9223,9224,9230,9231 \
  -j DROP
```

Only the four agent TCP ports are restricted; the WebRTC UDP ranges
(`52101-52300`) stay open for public viewers. The rules are applied at
boot by a systemd unit (`cb-cdp-fw.service`, see §6) — the host has no
netfilter-persistent.

Agent connects directly, e.g. `cdp-probe.py 10.0.5.1:9223` (or any
pmoc-lan address of mother01) / browser-use with `cdp://…:9223`. No ssh
-L forwards anywhere in the path.

### D6 conclusion — dedicated skill (2026-08-21)

Driving CloudBrowser slots is a **dedicated skill**, not the Hermes
standard `browser_exec` (which owns a local browser and does not know
about slots, wake, or fleet state):

- **Skill: `pmoc-cdp-cloudbrowser`** — **canonical copy in this repo**
  at `skills/pmoc-cdp-cloudbrowser/` (SKILL.md + `scripts/pmoc_cb.py` +
  vendored browser-use lib in `scripts/vendor/`); also mirrored into
  Hermes skills (category `pmo-city`). Vendors a **local copy of the
  browser-use library** and a CloudBrowser-aware driver
  `scripts/pmoc_cb.py`:
  `wake_slot()`, `health()`, `attach()`, plus the harness helpers
  (`js`, `list_tabs`, `switch_tab`, `close_tab`, `new_tab`, …).
- **Wake-first rule** (verified D6): slots idle-suspend
  (`IDLE_TIMEOUT_MIN=2`, `IDLE_ACTION=suspend`) — a suspended slot's CDP
  relay is up but Chrome is STOPPED → `ConnectionResetError`/curl `000`.
  Always `POST /restart` and poll `/health` until `cdp_ok: true` before
  connecting.
- D6 verification on the live fleet (direct pmoc-lan, no tunnel):
  attach → navigate → tab-switch → download (`d6-test.txt` landed in
  `slot-1-downloads` volume).

---

## 2. Volumes

| Volume | Mounted at | Holds |
|---|---|---|
| `*_scripts` (shared per stack) | `/etc/neko/supervisord:ro` (slots/viewer), `/app:ro` (router), `/data/scripts:ro` (janitor) | all supervisord programs + router code |
| `slot-1-profile` / `slot-2-profile` | `/home/neko/.config` | Chrome profile `google-chrome/` + CfT binary `cft-chrome-128/` |
| `viewer-profiles` | `/home/neko/.config/google-chrome-w1` | viewer profile + CfT binary inside profile |
| `slot-1-downloads` / `slot-2-downloads` / `downloads` | `/home/neko/Downloads` / `/data/downloads` | downloads (janitor + clamav scan) |
| `router-state` | `/data/state` | sticky session map `router-state.json` |
| `clamav-db` | `/var/lib/clamav` | virus signatures |

---

## 3. Scripts volume — canonical mapping (sha-verified 2026-08-20)

Repo base: `scripts/` in this directory. Deployed name = the name the
supervisord include dir actually sees (the image's own supervisord.conf
ignores non-`.conf` files; all `.conf` in the include dir auto-load).

### Fleet volume (W2) — deployed name → repo file
| Deployed | Repo file | Notes |
|---|---|---|
| `google-chrome.conf` | `26-s7-fleet-slot-chrome.conf` | CfT+kiosk+CDP via wrapper; re-declares openbox; cdp-relay program |
| `slot-prepare-chrome.sh` | `26-s7-fleet-slot-prepare-chrome.sh` | wrapper: lock cleanup → Preferences patch → exec CfT (kiosk, `--window-size=1920,1080`, CDP 9222, tabbar, start https://pmo.city) |
| `router-v2.py` | `router-v2.py` | router code (runs from `/app` in python:3.12-slim); **Host dispatch since 08-20**: cloudbrowser→8081, cloudfiles→9231 (D.3); **spec 29 coordinator**: `/fleet/release`, archive wake, `/identify` push + 30 s identity sweep (29b); **spec 31 v3 (2026-08-21)**: wait queue + landing "Open Browser" `?pwd=&usr=` auto-login, max-duration reaper, agent API, release/queue-entry hygiene + boot stale-drop (`CB_*` env surface; md5 `f6545e12`, sha256 `24d24f522c4f178434da7543ee2d63bb41f58139e3a8f55f0248ede75f62c3de` verified live 2026-08-21) |
| `restart-api.conf` | `26-s7-fleet-slot-restart-api.conf` | slot variant: PROFILE_DIR=/home/neko/.config/google-chrome |
| `restart-api.py` | `restart-api.py` | PROFILE_DIR-aware; **spec 29 reaper** (idle suspend/resume + archive + 29b slot identity); **spec 31 fresh wake** (no-archive user → empty-profile wake instead of 500; md5 `d6b7d6a8`, sha256 `e2222649…` verified 2026-08-21) |
| `cdp-relay.conf` / `cdp-relay.py` | same names | 0.0.0.0:9223 → 127.0.0.1:9222; **v3 touches `/tmp/cdp-activity` on C→U chunks** (agent signal for the reaper; md5 `83812991`) |
| `title-proxy.conf` / `title-proxy.py` | same names | 8081, rewrites `<title>` + injects toolbar |
| `downloads-api.conf` / `downloads-api.py` | `26-s7-fleet-slot-downloads-api.conf` (deployed as `downloads-api.conf`) / `downloads-api.py` | slot variant: DOWNLOADS_DIR=/home/neko/Downloads, :9231 (D8) |
| `slot-policy-init.conf` / `.sh` | same names | chrome policies init (slot) |
| `branding-init.conf` / `.sh` + `branding/` | same | neko UI branding (logo.800bec71.svg, app.909074c1.js) |
| `janitor.py` / `janitor-loop.py` | same names | download scan/cleanup loop |
| `tabbar-extension/` | same | MV3 tab bar (background.js, content.js, manifest.json) — **v1.8.0 content.js** (spec 29 grace-countdown toast; md5 `87bedac9`) |

### Viewer volume (W1) — deployed name → repo file
| Deployed | Repo file | Notes |
|---|---|---|
| `google-chrome.conf` | `chrome.conf` | same content (docs call it chrome.conf) |
| `prepare-chrome.sh` | same | viewer wrapper: kiosk + CDP + tabbar + `$PROFILE/cft-chrome-128/chrome` |
| `restart-api.conf` | `restart-api.conf` | viewer variant, NO PROFILE_DIR env (default = viewer profile) |
| `restart-api.py` | `restart-api.py` | unified |
| `cdp-relay.conf` / `.py`, `title-proxy.conf` / `.py`, `branding-init.*` + `branding/`, `janitor.py`, `janitor-loop.py` | same | identical to fleet copies (sha-verified) |
| `window-manager.conf` / `.py` | same | kiosk window pinning |
| `tooling-init.conf` / `.sh` | same | one-shot tooling init |
| `policy-init.conf` | same | chrome policies (translate off etc.) |
| `server.py` | same | fake-login server (legacy service) |
| `downloads-api.conf` / `.py` | same | downloads API (viewer-deployed; fleet later) |
| `sso-broker.conf` / `.py` | same | SSO broker (viewer; fleet W3) |

Ownership: `root:root`, 644 for `.conf`, 755 for `.sh` (slots' `restart-api.py`/`cdp-relay.py` run as root → 640/750 ok). Profile dirs and CfT binaries: `1000:1000` (neko).

### Kiosk window sizing (2026-08-21)

`--kiosk` + `--restore-last-session` (restore_on_startup=1) restored the
previous session's window geometry (e.g. 945×1060 at top-left on the
1920×1080 desktop), leaving a small window + black void. Fixed in the
wrapper: explicit `--window-size=1920,1080` + `restore_on_startup=5`
(fresh start; cmdline URL still opens pmo.city). **Staged 2026-08-21** —
applies at the next natural Chrome restart (janitor/OOM/manual relaunch).
Pilot workaround meanwhile: the tabbar **Relaunch Chrome** restore button
reloads the page at the right size (users should know this).

---

## 4. CfT 128 seeding (per profile volume)

Binary source of truth: viewer profile
`/home/neko/.config/google-chrome-w1/cft-chrome-128/`
(128.0.6613.137; the older `cft-chrome/` = 124 fallback).

```sh
# from the viewer container
docker cp viewer-<uuid>:/home/neko/.config/google-chrome-w1/cft-chrome-128 /tmp/cft-128
# into each fleet slot profile volume (volume root = /home/neko/.config)
docker cp /tmp/cft-128 slot-1-<uuid>:/home/neko/.config/cft-chrome-128
docker cp /tmp/cft-128 slot-2-<uuid>:/home/neko/.config/cft-chrome-128
docker exec slot-1-<uuid> chown -R 1000:1000 /home/neko/.config/cft-chrome-128
docker exec slot-2-<uuid> chown -R 1000:1000 /home/neko/.config/cft-chrome-128
```

Why CfT: stock Chrome 133/151 in the neko image have broken CDP sessions
(page-WS hang + `-32001`; proven by `scripts/cdp-probe.py` 2026-08-20).
CfT 128 is CDP-verified. `--kiosk --disable-infobars` hides the CfT notice
bar (verified; screenshot evidence in `26-s7-fleet-app.md`).

---

## 5. Reproduction steps (from zero)

1. **Coolify:** create a new stack; paste the authored raw compose from the
   spec; set env defaults if needed (`NEKO_SCREEN`, `NEKO_PASSWORD*`,
   `N_SLOTS`, `SLOT_PORT=8081`, `CLAMAV_HOST/PORT`, `QUOTA_BYTES`,
   `RETENTION_DAYS`, `HOME_URL` (default `https://pmo.city`),
   `TAB_LIMIT` (default 3)). Deploy → volumes auto-create.
2. **Domains** (UI, Domains tab): add `s7fleet.dev01.pmo.city` to router
   (tinyauth domain label already in compose); viewer stack:
   `cloudbrowser.*` + `cloudfiles.*`.
3. **Seed the scripts volume** per table §3 (docker cp; chown root; chmod
   644 conf / 755 sh).
4. **Seed CfT 128** per §4 (fleet slots; viewer already has it).
5. **Restart the stack** (or per-service: slots, router). Verify:
   - `docker ps` → all healthy (router/janitor/clamav healthchecks
     overridden in compose; slots keep the baked neko healthcheck).
   - `docker exec slot-N supervisorctl status` → google-chrome,
     cdp-relay, restart-api, title-proxy, openbox, x-server, neko
     RUNNING (branding-init/slot-policy-init EXITED = ok, one-shot).
6. **Verification battery:**
   - CDP: `python3 scripts/cdp-probe.py <slot-ip>:9223` → 5/5 PASS
     (agent path over pmoc-lan; no tunnel).
   - restart-api: `GET <slot-ip>:9230/health` → programs + cdp_ok.
     `POST .../restart` → chrome stopped→started.
   - Router: `curl -H 'Remote-Email: spike-user@aikumi.pro'
     http://<router-ip>:8081/` → `<title>Cloudbrowser: …</title>` +
     cb-email toolbar; sticky assignment spike-user→slot-1,
     montigaud→slot-2; third user → busy page.
   - Screenshot: `docker exec slot-N sh -c 'DISPLAY=:99 scrot -o
     /tmp/x.png'` → kiosk, tabbar, pmo.city homepage, no CfT banner.
   - Spec 27 (tabbar v1.5.0): `GET <slot-ip>:9230/config` →
     `{homeUrl, tabLimit}`; one pmo.city tab only (no pile-up); Home/Plus
     open tabs; at `TAB_LIMIT` tabs Home/Plus grayed + tooltip; restore
     capped at `TAB_LIMIT`.
     `{homeUrl, tabLimit}`; one pmo.city tab after clean restore; Home/Plus
     click-tested via CDP; at `TAB_LIMIT` tabs Home/Plus grayed + tooltip; restore
     capped at `TAB_LIMIT`.
   - Spec 27 S6 (tabbar v1.6.0): at `TAB_LIMIT` Home/Plus stay enabled —
     least-recently-used real tab is evicted (active tab never) and a toast
     names it; verify via `EXT_VERSION` in the SW context (`/json/list`,
     type=service_worker) and a 3-tab eviction probe on slot-2.

---

## 6. Live coordinates (pmoc-lan, 2026-08-20)

- router `10.0.34.2:8081`, slot-1 `10.0.34.5` (CDP relay 9223,
  restart-api 9230), slot-2 `10.0.34.6` (same).
- IPs move on container recreate → recompute:
  `docker inspect <name> --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}'`.
- **Agent access (2026-08-21):** CDP + restart-api are **published on
  the host** (`0.0.0.0:9223/9230` slot-1, `0.0.0.0:9224/9231` slot-2),
  reachable at any mother01 pmoc-lan address (e.g. `10.0.5.1`). Direct
  `ws://10.0.5.1:9223` — production path is pmoc-lan, **no SSH tunnel**.
- **Firewall (host, DOCKER-USER chain)** — restricts the four agent TCP
  ports to `10.0.0.0/8` (see §1 agent path). Applied at boot by
  `/etc/systemd/system/cb-cdp-fw.service`:

```ini
[Unit]
Description=CB fleet CDP agent-path firewall (DOCKER-USER, pmoc-lan only)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/bin/sh -c '/usr/sbin/iptables -D DOCKER-USER 3 -p tcp -m multiport --dports 9223,9224,9230,9231 -j DROP 2>/dev/null; /usr/sbin/iptables -D DOCKER-USER 2 -p tcp -m multiport --dports 9223,9224,9230,9231 -s 10.0.0.0/8 -j ACCEPT 2>/dev/null; /usr/sbin/iptables -D DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null; true'
ExecStart=/usr/sbin/iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
ExecStart=/usr/sbin/iptables -I DOCKER-USER 2 -p tcp -m multiport --dports 9223,9224,9230,9231 -s 10.0.0.0/8 -j ACCEPT
ExecStart=/usr/sbin/iptables -I DOCKER-USER 3 -p tcp -m multiport --dports 9223,9224,9230,9231 -j DROP

[Install]
WantedBy=multi-user.target
```

  `systemctl enable --now cb-cdp-fw.service` — idempotent (flushes the
  three rules first, then re-inserts). DOCKER-USER is flushed on docker
  restart; the unit re-applies via `After=docker.service`.

---

## 7. Ops notes (learned the hard way)

- **Tabbar deploy = clear the SW cache.** Chrome caches the MV3
  service-worker script per-profile in
  `$PROFILE/Default/Service Worker/ScriptCache`. After deploying a new
  `background.js`: stop Chrome, `rm -rf` that dir (the root-level
  `Service Worker/` is vestigial — not the cache), start. Skip this and
  the SW runs stale code (verified 2026-08-21: manifest 1.5.0 on disk,
  running SW v1.4.0/v1.2.0).
- **Planned Chrome restarts: use `POST :9230/restart`, not
  `supervisorctl stop/start`.** Only restart-api (or its CDP watchdog)
  restores the D5 tab snapshot; a manual supervisorctl restart parks the
  browser at newtab with zero tabs.
- **Coolify API:** prod key rejects the gateway's egress IP ("You are not
  allowed to access the API" on ALL endpoints). Workaround:
  `scripts/coolify-local.sh` (SSH → localhost:8000, token from the gateway
  process env — never echoed). TODO for Tigo: re-check the key's
  allowed-IPs in the Coolify UI, or the gateway loses API access
  permanently.
- **Compose renderer:** rewrites only `${VAR:-default}`; bare `${VAR}` →
  empty. Never paste rendered output back into the repo.
- **Healthchecks:** baked checks break when apps stop image services
  (viewer stack: the legacy browser/fake-login are still in the compose —
  keep them). Fleet compose overrides router + janitor healthchecks.
  **Spec 29 mandate (2026-08-21): every container should have one — fleet
  slots + viewer stack still lack them; pending (see spec 29 §11).**
- **Spec 29 idle suspend/resume:** fleet slots suspend idle sessions
  (defaults `IDLE_TIMEOUT_MIN=15` / `IDLE_GRACE_MIN=5` /
  `IDLE_CHECK_INTERVAL=60`; live test values 2/1/10), archive to
  `sessions:/data/sessions`, release via router `/fleet/release`, wake on
  return. Router identity sweep (`IDENTIFY_SWEEP_INTERVAL=30`) keeps
  `.slot-user.json` fresh in each slot's Downloads. Viewer pinned
  `IDLE_ACTION=none`. Full detail + the two post-deploy fixes:
  `29-idle-suspend-resume.md` §10–11.
- **Watchtower:** scope `monitor-notify` (no auto-update).
- **Tab persistence (D5):** restart-api snapshots open URLs every 30 s and
  restores them after Chrome restarts; session cookies survive via Chrome's
  cookie DB.
- **Known W2 deltas still open:** healthchecks on fleet slots + viewer
  stack (spec 29 §11); downloads-api on slots is DONE (cloudfiles route
  live since 08-20). Idle-stop refinement: **DONE via spec 29**.
