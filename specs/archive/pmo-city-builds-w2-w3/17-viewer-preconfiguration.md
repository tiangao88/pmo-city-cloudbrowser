# 17 — Viewer pre-configuration (W1 implemented state)

> Status: **✅ IMPLEMENTED + VERIFIED 2026-08-17** (dev01, W1 POC);
> extended **2026-08-18** (W2: title-proxy, tab bar D14, downloads-api,
> restart-api, tooling-init, drift pin — §2/§6).
> This is the authoritative record of how a fresh `viewer` container
> reaches a usable state: Chrome for Testing 128, CDP relay, Bitwarden
> extension pre-installed + pinned + pointed at the Vaultwarden, crash-safe
> supervision, preinstalled tooling. The template mirror (placeholder-safe)
> lives in `hermes-cloudbrowser/docs/viewer-preconfiguration.md`.

## 1. Target state (what "preconfigured" means here)

| # | Item | Verified |
|---|---|---|
| 1 | Browser = CfT 128.0.6613.137 (pinned path), not distro Chrome | ✅ live |
| 2 | CDP relay 0.0.0.0:9223 (agent drives over pmoc-lan, no tunnels) | ✅ live |
| 3 | Bitwarden extension force-installed | ✅ policy + `docker restart` survived |
| 4 | Bitwarden pinned in toolbar (icon at 1735,62 @1920×1080) | ✅ survives `supervisorctl restart` |
| 5 | Vault URL preconfigured → popup "Accessing: self-hosted" (secrets.pmo.city) | ✅ survives restart |
| 6 | Crash-safe: startretries=5 + Singleton-cleanup wrapper + ulimits nofile | ✅ incident §8 of `10-w1-status.md` |
| 7 | `session.restore_on_startup=1` patched at boot | ✅ Chrome-native restore still broken (CfT 128 writes no snapshot); **D5 agent-managed snapshot in `restart-api.py`** restores tabs across restarts/recreates |

## 2. File inventory + wiring (canonical: `hermes-cloudbrowser/spike/viewer-neko/`)

| File | supervisord program | Role |
|---|---|---|
| `chrome.conf` | `google-chrome` | Launch definition: `command=prepare-chrome.sh`, `startretries=5`, env, autorestart |
| `prepare-chrome.sh` | — | Singleton-lock cleanup + Preferences patch (restore_on_startup=1, pin keys) + `exec` CfT 128 |
| `policy-init.conf` | one-shot `priority=1` | `cp bitwarden-policy.json /etc/opt/chrome_for_testing/policies/managed/` at every boot |
| `bitwarden-policy.json` | — | `ExtensionSettings` force_installed Bitwarden |
| `cdp-relay.py` | `cdp-relay` | TCP pipe 127.0.0.1:9222 → 0.0.0.0:9223, `settimeout(None)` (10 s idle-recv killed long CDP sessions) |
| `bw-preconfig.py` | agent-side | CDP → extension SW → vault-URL storage write (§4.4) |
| `window-manager.conf/.py` | `window-manager` | Minimal WM on `:99` |
| `title-proxy.conf/.py` | `title-proxy` | :8081 — rewrites the neko window title to `Cloudbrowser: <email>` (tinyauth `Remote-Email` header), relays WS signaling; `settimeout(None)` after connect (120 s neko heartbeat) |
| `downloads-api.py/.conf` | `downloads-api` | :9231 file-list server: HTML list (viewer) + `/api/files` + `/dl/<name>` (agent); quarantine badges |
| `janitor-loop.py` + `janitor.py` | (janitor container) | 60 s scan-at-ingest loop; ClamAV moves infected → `.quarantine/` (preserved) |
| `restart-api.py/.conf` | `restart-api` | :9230 — health, `POST /restart` (supervisorctl restart google-chrome, tab snapshot/restore D5), `MAX_RUNNING_BROWSERS` fleet gate |
| `tooling-init.sh/.conf` | one-shot `priority=0` | apt xdotool+curl+jq per boot; disables the image's `dl.google.com` repo (NO_PUBKEY breaks `apt-get update`) |
| `tabbar-extension/` | (extension via `--load-extension`) | MV3 tab bar — see §6 |
| `translate-policy.json` | — | `{"TranslateEnabled": false}` policy overlay |
| `server.py` (base image) | — | neko image leftover (fake-login spike server) — superseded, kept inert |

Wiring: scripts volume `4guplgcrvug7l7h64m2cxkm1_scripts` mounted at
`/etc/neko/supervisord/` (supervisord include dir — `.conf` files there
become programs). Profile volume `…_viewer-profiles` holds
`/home/neko/.config/google-chrome-w1` (cookies, logins, pin, env —
survives recreates). Compose `ulimits: nofile 524288` on viewer + browser.

## 3. Chrome for Testing (why the pin)

- Watchtower auto-updated `ghcr.io/m1k1o/neko/google-chrome:2.9.0` (mutable
  tag) → Debian Chrome 133 → `FATAL … web_app.WebAppProto` + broken CDP.
  CfT 128.0.6613.137 is the known-good CDP target (Chrome 151/133 broken).
- Binary kept at `/home/neko/.config/google-chrome-w1/cft-chrome-128/chrome`
  (profile volume → survives recreates); fallback dir `cft-chrome/` (CfT 124).
- Full flag set (live chrome.conf): `--no-sandbox --window-position=0,0
  --display=:99 --user-data-dir=/home/neko/.config/google-chrome-w1
  --no-first-run --start-maximized --bwsi --force-dark-mode
  --disable-file-system --disable-gpu --remote-debugging-port=9222
  --remote-debugging-address=0.0.0.0 --remote-allow-origins=*
  --disable-dev-shm-usage --download-default-directory=/data/downloads
  https://example.com`.
- `--no-sandbox` is expected (root in-container) — NOT fixed in W1;
  boundary = container + tinyauth gate; W2/W4 hardening: non-root PUID/PGID.

## 4. Bitwarden extension — pre-install, pin, vault URL (full detail)

Extension ID `nngceckbapebfimnlniiiahkandclblb`, version 2026.7.0_0.

### 4.1 Force-install (policy)

`bitwarden-policy.json` (Bitwarden official Linux/Chrome schema;
`ExtensionSettings` supersedes `ExtensionInstallForcelist`):
```json
{ "ExtensionSettings": { "nngceckbapebfimnlniiiahkandclblb": {
    "installation_mode": "force_installed",
    "update_url": "https://clients2.google.com/service/update2/crx" } } }
```
**CfT policy path is `/etc/opt/chrome_for_testing/policies/managed/`** —
NOT `/etc/opt/chrome/policies/`. Verified: binary strings of CfT 128
contain `etc/opt/chrome_for_testing/policies`; a test policy in the
chromium path did nothing; `chrome://policy` loads but ignores it. The
neko image's own policies (uBlock `cjpalhdlnbpafiamejdnhcphjbkeiagm`,
SponsorBlock `mnjggcdmjocbbbhaepdhchncahnbgone`, blocklists) at
`/etc/opt/chrome/policies/managed/policies.json` therefore **never applied
to CfT** (profile has zero extension dirs) — migrating them to the CfT
path is a W2 option.
`policy-init.conf` copies the JSON at every boot because container `/etc`
is ephemeral (a plain `docker cp` dies with the container).

### 4.2 What CfT does NOT support

CfT has enterprise features stripped: a per-extension-ID policy key logs
`… has an error of type: Unknown policy` and `chrome.storage.managed`
stays `{}`. Bitwarden documents **no server-URL policy key** at all ⇒
the URL must be preconfigured by storage write (4.4).

### 4.3 Pin (the hard-won part)

- Pre-written prefs `extensions.settings.<id>.pin_to_toolbar=true` +
  `extensions.pinned_extensions=["<id>"]` (both survive Chrome's flush —
  verified after `supervisorctl stop`) are **ignored at boot by CfT 128**.
- **Working path = real UI action** (xdotool, apt-installed in viewer):
  1. click extensions puzzle **(1771, 63)** → dropdown opens
  2. click the pin icon on the Bitwarden row **(1701, 225)**
  3. icon now pinned at **(1735, 63)**; Chrome itself wrote the same two
     keys the wrapper pre-writes.
- Pin state persists across `supervisorctl restart` (verified 21:5x).
- `prepare-chrome.sh` keeps pre-writing both keys (belt-and-braces for
  future Chrome builds); W2: bake xdotool + one-time click at first boot
  (apt-install is ephemeral — container recreate loses xdotool).

### 4.4 Vault URL preconfig — the `__json__` envelope

Popup "Accessing: bitwarden.com" until the extension's own dialog is
driven (Accessing row (1511,656) → "self-hosted" (1566,620) → Server URL
(1511,487) → type `https://secrets.pmo.city` → Save (1329,640) → green
banner "Environment URLs saved").

Reading back storage (CDP → service worker) shows the **exact** shape:
```json
global_environment_environment = {
  "__json__": true,
  "value": "{\"region\":\"Self-hosted\",\"urls\":{\"base\":\"https://secrets.pmo.city\",\"api\":null,\"identity\":null,\"webVault\":null,\"icons\":null,\"notifications\":null,\"events\":null,\"keyConnector\":null,\"send\":null}}"
}
global_environment = { "base": "https://secrets.pmo.city" }
```
`bw-preconfig.py` writes both via `chrome.storage.local.set` from the
extension service worker. ⚠️ A **raw** object under
`global_environment_environment` is silently ignored (the earlier failed
attempt — popup stayed on cloud). After a full restart the popup reads
**"Accessing: self-hosted"** with the login page for the Vaultwarden.

### 4.5 Persistence & limits

- Cookies/logins/pin/env live in the profile volume → container recreates
  are safe (policy-init re-copies the policy at boot).
- A `Default/` **rebuild** (incident recovery) re-installs the extension
  (policy) but loses logged-in session + pin (W2).
- First unlock is the user's master password — the extension's locked
  state is the natural entry point; per-user unlock + hybrid 2FA (FR-5/6)
  is the W2 plan. No master password is ever stored.

## 5. Preinstalled tooling (automation prerequisites)

Inside the viewer (`ghcr.io/m1k1o/neko/google-chrome:2.9.0`), verified 2026-08-17
+ 2026-08-18 (D11):

| Tool | In image | Used by | State |
|---|---|---|---|
| python3 | ✅ `/usr/bin/python3` | cdp-relay, janitor, window-manager | — |
| bash / sh | ✅ | wrappers, health checks | — |
| wget | ✅ | HTTP probes from inside the container | — |
| supervisorctl | ✅ | process supervision/restart | — |
| xdg-open | ✅ | (neko UI) | — |
| **xdotool** | ❌ → **tooling-init** | save-dialog dismissal (display :99), pin bootstrap | ✅ **D11: start-script apt** |
| scrot | ❌ | screenshots for UI verification | ⏳ W2-pending (not in D11 DoD) |
| curl / jq | ❌ → **tooling-init** | debugging convenience, fleet/health probes | ✅ **D11: start-script apt** |
| git | ❌ (not needed in container) | — | — |

Automation runs from the **agent** container (`/opt/data/cdp-venv`), never
from the viewer. **The agent automation layer is the browser-use library
over CDP** — chosen for **token efficiency, a fundamental criterion**: the
latest version prunes the DOM and exposes compact element context, so LLM
token consumption per action stays minimal (the dominant cost lever on a
fleet of persistent browsers). W1 demo-day fallback: Playwright
`connect_over_cdp` (browser-use session manager flaked during the download
demo; re-validate in W2 — the product path stays browser-use).

**D11 implementation (2026-08-18) — start-script apt, chosen over a custom
image** (no image to build/maintain; works against any neko tag):
- `tooling-init.sh` + `tooling-init.conf` (supervisord **one-shot**,
  `priority=0` — runs BEFORE policy-init/chrome at every boot; the scripts
  volume is the canonical copy, see §2 inventory).
- Logic: if xdotool/curl/jq missing → `apt-get update` + install
  (`--no-install-recommends`), 3 retries, log to
  `/var/log/neko/tooling-init.log`.
- **Pitfall (fixed):** the image ships `/etc/apt/sources.list.d/
  google-chrome.list` whose key is missing in-container (NO_PUBKEY
  FD533C07C264648F) — that makes `apt-get update` **fail outright**
  (W1's "not signed" warning is fatal in W2's Debian state). The script
  disables the google repo for the pass (`mv .list .disabled`); the distro
  Chrome it would install is never used (CfT 128 runs from the profile).
- **Verified through a real container recreate:** the D9 deploy (2026-08-18)
  recreated the viewer; all three tools came back
  (xdotool/curl/jq ✅), one-shot EXITED clean.

## 6. Drift-pin strategy (D11)

W1 FATAL incident: watchtower drifted Chrome 128 → 133 once (10-w1-status
§8). CfT-in-profile was a *mitigation*; D11 makes the drift *impossible*
across a watchtower cycle, with **three independent pins**:

1. **Image tag pinned** — compose references `ghcr.io/m1k1o/neko/
   google-chrome:2.9.0` (no `latest`); watchtower scope `monitor-notify`
   (notify-only, no auto-update). A forced watchtower run can only
   recreate the SAME image.
2. **Chrome binary lives in the profile volume** —
   `$PROFILE/cft-chrome-128/chrome` (CfT 128.0.6613.137, ~248 MB,
   downloaded once into the persistent volume). Image refreshes can't
   touch it; a full container recreate re-launches the same binary.
3. **Launch path pinned in the scripts volume** — `prepare-chrome.sh`
   + `chrome.conf` (supervisord) point at the profile binary, not at any
   in-image chrome. The scripts volume is the canonical copy (repo
   mirror), so even a wiped container fs re-pins on recreate.

**Verification (2026-08-18):** the D9 deploy recreated the viewer
container (equivalent to a watchtower cycle); after boot the browser was
still `Google Chrome for Testing 128.0.6613.137`, tabs restored via D5.

## 7. Verification checklist (post-deploy, dev01)

```bash
# CDP round-trip
curl http://10.0.37.9:9223/json/version          # → Chrome 128.0.6613.137
# extension policy present (in-container)
docker exec viewer-4guplgcrvug7l7h64m2cxkm1 sh -c \
  'ls /etc/opt/chrome_for_testing/policies/managed/ && \
   cat /etc/opt/chrome_for_testing/policies/managed/bitwarden-policy.json'
# supervisor state
docker exec viewer-4guplgcrvug7l7h64m2cxkm1 supervisorctl status
```
UI checks (1920×1080): popup footer "Accessing: self-hosted"; shield
pinned at (1735,63); `chrome://policy` shows ExtensionSettings.

## 8. W2 hardening (explicitly NOT in W1)

1. **Real "restart Chrome" button** (Tigo ask): tiny HTTP endpoint in the
   viewer (CDP-relay pattern) → `supervisorctl restart google-chrome`;
   neko has no app-launch UI (admin menu restarts only the neko server).
2. **Pin bootstrap**: xdotool baked into image + one-time puzzle→pin click
   on fresh profiles.
3. **Watchtower pin strategy** (CfT-in-conf is a mitigation, not a pin).
4. **Janitor CDP watchdog** (auto-restart on unresponsive relay).
5. Per-user unlock / hybrid 2FA (FR-5/6); extension state across profile
   rebuilds; migrate image uBlock/SponsorBlock policies to the CfT path.
6. Tooling image (`FROM neko:2.9.0` + xdotool/curl/jq/scrot).

## 9. Tab bar extension (D14 — implemented 2026-08-18)

`tabbar-extension/` (MV3, loaded via `--load-extension=/etc/neko/
supervisord/tabbar-extension` in `chrome.conf`) injects a slim dark bar
into every top-frame page (shadow DOM, `z-index: 2147483647`). The
extension is the kiosk user's tab/navigation UI — neko itself has none.

| Button | Action |
|---|---|
| `«` | collapse the bar to an 18 px strip (state: per-site `localStorage`, key `cb_tabbar_collapsed`) |
| `←` / `→` | history back / forward on the active tab (`chrome.tabs.goBack/goForward`; no-history errors swallowed → silent no-op) |
| `↺` | reload the active tab |
| `↻` | relaunch Chrome — POST `http://127.0.0.1:9230/restart` (restart-api → `supervisorctl restart google-chrome`; tabs restored via D5 snapshot) |
| `▲` | cycle the bar edge: top → right → bottom → left, glyph shows the current edge. State: `chrome.storage.local` key `cbBarPos` → **every tab's bar moves together**; survives page reloads |
| tab pills | click to switch; `×` closes the tab (hidden when only one tab remains) |

> v1.4.0 (2026-08-18): `＋`, `🔒 Vaultwarden` and `📁 Files` were removed
> from the tab bar — it is pure navigation now. App shortcuts live in the
> **client toolbar** (title-proxy injection): they open in the PARENT
> browser via `target="_blank"`, so Vaultwarden/Cloud files sessions and
> downloads land on the user's machine, not in the kiosk Chrome.

Design notes:
- All chrome.tabs work runs in `background.js` (service worker, id
  `hpmocjampkhacpfdabdjblmfkifgkjpd`); the content script only renders +
  forwards messages. `chrome.runtime.onMessage` returns `true` (async
  response).
- Back/forward/reload/relaunch act on the **active** tab; the content
  script asks the SW for it (`chrome.tabs.query({active,currentWindow})`).
- Chrome error/crash pages (`chrome-error://`) and the neko internal UI
  get no bar (content script doesn't run there).
- The bar appears after Chrome crash+auto-restart (supervisord
  `startretries=5`): same launch flags → extension reloads → tabs
  restored (D5) → bar back on them; the crash page itself stays bar-less.

**Verification (2026-08-18):** all four positions cycled with real
pointer clicks (xdotool on `:99`) — rects flush to the chosen edge
(right `[1726,0,178,1079]`, bottom `[0,1053,1904,26]`, left
`[0,0,178,1079]` @1920×1080); tabs re-stack vertically on left/right;
a second tab's bar moved in lock-step (`cbBarPos` sync); position
survived a page reload. Back/forward/reload verified by URL + history
index + navigation-type probes.

---

*Revision: 2026-08-18 — D14 tab bar §9; full scripts mirror of the live
volume (cdp-relay, downloads-api, janitor-loop, restart-api,
window-manager, tooling-init, chrome.conf, policies) added to
`scripts/`. Earlier: D11 additions (§5 tooling start-script apt, §6
drift-pin strategy; D8 downloads-api + D9 fleet gate recorded in
`20-w2-dod.md`). Base: 2026-08-17 — initial record of the implemented W1
pre-configuration (extension force-install, pin, vault-URL envelope, CfT
pin, tooling gaps). Companion: `10-w1-status.md` §8 (crash incident), §9
(tooling inventory), §10 (extension); template mirror
`hermes-cloudbrowser/docs/viewer-preconfiguration.md`.*
