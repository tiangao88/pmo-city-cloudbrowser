# W1 Status — audit vs specs (2026-08-17)

> Working status of the W1 POC (dev01, due Aug 23) against the specs.
> Updated as W1 progresses. Legend: ✅ done · ⚠️ partial / over-claimed · ❌ not done.
> **W1 CLOSED 2026-08-17** — all DoD items ✅ (see §0); one-page summary
> delivered (`18-w1-summary.md`); open items below are explicitly W2.

**W1 goal:** prove the full chain for ONE user on ONE browser + produce the
numbers W2–W4 depend on. **Checkable outcome (reworded 2026-08-17, Tigo
decision):** click the link on dev01 → land in a live browser; watch the
agent drive it from chat; download a file → ask the agent for it in chat
(in-viewer file list is a W2 build); quota + virus-scan working; one-page
summary handed to Tigo (viewer choice + RAM numbers + broker verdict).

---

## 0. Definition of Done (W1) — **CLOSED 2026-08-17** (8/8 ✅)

| # | DoD item | Status | Latest evidence |
|---|---|---|---|
| 1 | Link on dev01 → SSO → live browser | ✅ | `auth.pmo.city` (tinyauth-pmo) → Aikumi Connect → **group gate PMOC_Users** (was AKP_IT_Admin; widened by Tigo 2026-08-17) → n.eko viewer, live Chromium. Human-verified by Tigo twice (screenshots). |
| 2 | Agent drives the browser from chat (FR-4) | ✅ | **browser-use library over CDP** — the token-efficient automation layer (fundamental criterion, see §4); relay **tunnel-free over pmoc-lan** since 2026-08-17 (agent container on pmoc-lan; `viewer-4gupl…:9223` direct). Chrome 128.0.6613.137 (CfT). |
| 3 | Download → ask agent → get file in chat (FR-12) | ✅ | **Outcome reworded 2026-08-17 (Tigo decision):** retrieval happens in chat via the agent, not in the viewer. Mechanics proven (files land in `/data/downloads`, retrievable via agent/`docker exec cat`; demo capture `cb-demo-download.pdf`). In-viewer file list remains a W2 build. |
| 4 | Quota + virus-scan working | ✅ | janitor (quota 5 GB / retention 90 d) + ClamAV scan-at-ingest live (dev01). |
| 5 | One-page summary (viewer choice + RAM + broker verdict) | ✅ | `18-w1-summary.md` — committed 2026-08-17 (due Aug 23). Includes EU residency (D4): **mother01 hosted in Helsinki, FI (EU/GDPR)** — Tigo-confirmed 2026-08-17. |
| 6 | Migration to pmoc-lan, tunnel-free, volumes migrated, old stack destroyed | ✅ | 2026-08-17: agent + viewer on pmoc-lan (`10.0.37.x`), volumes tar-copied (viewer-profiles 1.2 GB, clamav-db 168 MB, …), old stack `ism3def5kz88edlerxakcun1` **destroyed by Tigo**. |
| 7 | Chrome resilience (crash → self-heal) | ✅ | 2026-08-17: `ulimits nofile 524288` (viewer+browser), `startretries=5`, Singleton-cleanup wrapper, CfT 128 pinned in conf. See §4. |
| 8 | Vaultwarden extension preinstalled in viewer Chrome | ✅ | 2026-08-17: policy-based force-install (Bitwarden **2026.7.0**) via CfT enterprise policy + supervisord one-shot; survives container restart. See §10. |

---

## 1. End-to-end chain (happy path) — specs FR-1/FR-2/FR-3/FR-4

| Item | Status | Evidence / notes |
|---|---|---|
| Link → SSO → browser | ✅ | 2026-08-17: `auth.pmo.city` (tinyauth-pmo) → Aikumi Connect → group gate **PMOC_Users** (widened from AKP_IT_Admin by Tigo; live compose label confirmed) → n.eko viewer live Chromium (Tigo human-verified). **Re-verified full flow by Tigo same day (screenshots):** Aikumi Connect login → n.eko login (admin) → live viewer showing the Wikipedia page the agent had loaded. **W1 login gate PASSED 2026-08-17.** |
| Agent control | ✅ | 2026-08-17: **agent drives the viewer's Chrome** through a CDP relay (loopback 9222 → :9223, supervisord) — **tunnel-free over pmoc-lan** (agent container attached to pmoc-lan; connect by resolved IP because Chrome 119+ rejects CDP HTTP requests whose `Host` header is a hostname — 500 "Host header is specified and is not an IP address or localhost"). Playwright `connect_over_cdp`: connect / navigate / extract / screenshot proven live (screenshot: Wikipedia "cloud browser" search, 281 KB). Blocker found & fixed: the relay's `create_connection(timeout=10)` left a 10 s idle recv timeout killing every long-lived CDP connection (~10 s after open) — `settimeout(None)` now (cdp-relay.py v2, instrumented). CfT 124 → 128.0.6613.137 (`cft-chrome-128`; 124 kept as fallback). **Agent automation layer = the browser-use library over CDP** — chosen for
**token efficiency, a fundamental criterion** (latest version: DOM pruning +
compact element context ⇒ minimal LLM tokens per action; on a fleet of
persistent browsers this is the dominant cost lever). W1 demo-day run used
Playwright `connect_over_cdp` (browser-use's session manager flaked during
the download demo; re-validate in W2 — the product path stays browser-use). Commits: hermes-cloudbrowser `3c48b2a` (relay fix + demo scripts `browseruse-demo.py` / `browseruse-shot.py`). |
| Persistence | ✅ **CLOSED (D5, 2026-08-17)** | Profile volume proven: cookies, logins, history, CfT 128 binaries survive container recreates. **Open tabs now restore** via agent-managed tab snapshot (D5 mechanism pick, 2026-08-17): `restart-api.py` snapshots the http(s) page-URL list to `$PROFILE/tab-snapshot.json` every watchdog tick (30 s) and re-opens it after ANY Chrome (re)start — watchdog crash-restart, `POST /restart`, container restart (boot-restore). **Why not Chrome-native:** CfT 128 never wrote a restorable session — `Sessions/` holds orphaned `Session_`/`Tabs_` token pairs (tokens don't match → nothing restorable), no `Last Session`/`Last Tabs` written on stop (`exit_type: Crashed` persisted), and both the startup URL and `--kiosk` override `--restore-last-session` (verified: URL-drop and no-kiosk boots still opened `chrome://newtab`). `stopwaitsecs=30` kept (harmless, helps cookie flush). **Session cookies survive all restarts** — Chrome persists the cookie DB periodically (verified: CRM SSO still logged in after 4 restarts incl. container restart). Verified end-to-end on the live viewer: `POST /restart` ×2 + `docker restart` → CRM tab restored, single tab (no dupes, newtab closed), logged in. Record: 22-w2-progress.md; code `restart-api.py` (D5) mirrored in hermes-cloudbrowser. *(2026-08-17 evening: migrated profile rebuilt after corruption incident — see §8.)* |
| Simultaneity | ✅ | neko streaming + agent CDP client attached to one endpoint at the same time (2026-08-17). |
| Always-fullscreen viewer chrome | ✅ | neko's Xvfb has no WM → `--start-maximized` is a no-op; `window-manager` supervisord watcher (pure stdlib CDP) pins all windows to 1920×1080 every 4s, 30s cooldown. Live 2026-08-17; mirrored `hermes-cloudbrowser` `fa807f7`. |

## 2. Tinyauth wiring — FR-3

| Item | Status | Evidence / notes |
|---|---|---|
| 5 labels + middleware on viewer | ✅ | `tinyauth-pmo.apps.<uuid>.oauth.groups=PMOC_Users` (widened from AKP_IT_Admin by Tigo 2026-08-17), `.config.domain=cloudbrowser.dev01.pmo.city`, `tinyauth-pmo@file` appended to https route. |
| tinyauth duplicated for pmo.city family | ✅ | Second instance `tinyauth-pmo` at `auth.pmo.city` (single-domain-family root cause documented; template mirror `a678b65`). |
| Group gate — allowed path | ✅ | Aikumi Connect session through to viewer (2026-08-17). |
| Group gate — **denial path** | ❌ | Non-member → 403 still untested — **W2**. |

## 3. Viewer decision — FR-15

| Item | Status | Evidence / notes |
|---|---|---|
| Spike neko vs noVNC | ✅ | Both attached to the CDP-controlled Chromium on dev01. |
| Decision recorded | ✅ | `09-viewer-evaluation.md` — neko wins (WebRTC, audio, input latency, attach mechanics). Engine: Chrome for Testing 128.0.6613.137 (`cft-chrome-128`, 2026-08-17; 124 kept as fallback at `cft-chrome/`; neko stock Chrome 133/151 have broken CDP sessions — root cause documented in chrome.conf header). |

## 4. Broker feasibility — FR-7/FR-9 (spike only; OIDC → W2)

| Item | Status | Evidence / notes |
|---|---|---|
| Minimal broker spike | ✅ | Fake login page + one Vaultwarden item → server-to-server fetch → CDP form fill → `login-ok` on the viewer's own chrome; plaintext never in agent context/logs (b64 pipe 0600 + shred). |
| OIDC/M365 check | ❌ | Deferred to W2 (Vaultwarden OIDC vs Aikumi Connect) — Tigo 2026-08-16. |

## 5. Numbers for FR-16 (capacity params)

| Item | Status | Evidence / notes |
|---|---|---|
| Measurement recorded | ✅ | 2026-08-17: numbers in repo — `16-capacity-measurements.md`. Container cgroup: ~431 MiB idle → ~471 MiB loaded (Wikipedia); CPU ~107–146 % idle, 244 % load peak; Chrome 12 procs/1068 MB RSS; neko 267 MB; **no container memory limit set** (→ 2 GB `--memory` recommended at deploy). FR-16 locks (MAX_RUNNING_BROWSERS 5, ~1–2 GB/container, reserved slots, unlimited parked) recorded. |
| One-page summary (viewer choice + RAM numbers + broker verdict) | ❌ | Deliverable pending (due Aug 23). |

## 6. Repo + scaffold

| Item | Status | Evidence / notes |
|---|---|---|
| `hermes-cloudbrowser` private template-only repo | ✅ | README, AGENTS.md, license placeholder, W1 skeleton (compose + Chromium + CDP + volumes); PMO-secret scrubbed (2026-08-16 remediation). |
| POC runbook | ✅ | `docs/w1-runbook.md`; template mirror discipline (repo = canonical, volume = copy). |

## 7. Downloads (FR-12) — partially W1

| Item | Status | Evidence / notes |
|---|---|---|
| Durable per-user volume | ✅ | Browser download dir = per-user volume (flat area, survives browser destroy). |
| Quota 5 GB / 90 d / GDPR erasure | ✅ | Decided (pulled from W2, Tigo 2026-08-16). |
| ClamAV at ingest | ✅ | 2026-08-17 verified: benign→OK, EICAR→QUARANTINED. **2026-08-18 (D8): scan-at-ingest made real** — janitor container now runs `janitor-loop.py` (60 s loop, compose command), no more manual triggers; EICAR re-test → `QUARANTINED eicar-test.pdf → .quarantine/1787013400_eicar-test.pdf`, file preserved, janitor log = notification surface. |
| Viewer file list | ✅ **D8 (2026-08-18)** | `downloads-api.py` :9231 in viewer (HTML list, auto-refresh 3 s, open inline / download attachment, quarantine badges; `/api/files` JSON for the agent). |
| Chat access (agent lists/sends files) | ✅ **D8 (2026-08-18)** | `GET /api/files` + `GET /dl/<name>` — /dl/1MB.zip byte-identical to disk; same surface the agent uses for "list my downloads / send me file X". |

---

## ⚠️ Known contradictions / gaps found by this audit

1. ~~**Roadmap internal contradiction:** checkable outcome (Aug 23) says
   "download a file → see it in the viewer", but viewer file list is a W2
   item — impossible to check in W1 as written.~~ → **resolved 2026-08-17
   (Tigo decision): outcome reworded** to "ask the agent for it in chat";
   in-viewer file list stays a W2 build.
2. **FR-2 tabs-survive** was over-claimed ([x] with only cookie/session
   persistence proven) — restore_on_startup fix now applied (see §1).
3. ~~**FR-4 browser-use** was over-claimed (raw CDP demo marked as
   "MCP/browser-use over CDP")~~ → **resolved 2026-08-17**: browser-use wired
   and proven live (§1).
4. ~~**FR-16 raw numbers** missing from repo~~ → done 2026-08-17
   (`16-capacity-measurements.md`)
5. **Spec items with no W1 coverage (not forgotten, just tracked):**
   - ~~Screenshot/extract via agent (FR-4 full control)~~ → done 2026-08-17 (§1)
   - ~~EU residency (D4)~~ → **done 2026-08-17**: mother01 hosted in
     Helsinki, FI (EU/GDPR), Tigo-confirmed; public IP 145.223.34.130
     (Hostinger AS47583 — geo-IP DB nominally FR/Paris, both EU)
   - "Viewer idle timeout vs never expires" tension (`09-viewer-evaluation.md` §FR-16)
   - Group gate denial path (W2)

## Next actions (from this audit)

1. ~~Apply `session.restore_on_startup=1`~~ → applied 2026-08-17 (see §1)
2. ~~Wire browser-use → neko~~ → **done 2026-08-17**: `cdp-relay.py` (loopback
   9222 → :9223, supervisord, `settimeout(None)`), **tunnel-free over pmoc-lan
   since the migration** (agent container on pmoc-lan; connect via resolved IP
   — Chrome 119+ Host-header check). Playwright `connect_over_cdp` is the
   working path **on the demo day**; the **product automation layer is the
   browser-use library** (token efficiency = fundamental criterion — see §4);
   re-validate browser-use on the download flow in W2. Demo scripts
   in repo (`browseruse-demo.py` / `browseruse-shot.py`). Note: Chrome allows ONE
   active browser-level ws per browser — a new connection kicks the old one;
   avoid concurrent long-lived CDP clients.
3. ~~Record RAM/CPU numbers in repo~~ → done 2026-08-17 (`16-capacity-measurements.md`)
4. ~~Deliver one-page summary~~ → **done 2026-08-17**: `18-w1-summary.md`
5. ~~Resolve checkable-outcome contradiction~~ → **done 2026-08-17 (Tigo
   decision): reworded** — download retrieval in chat, viewer file list → W2

**W1 CLOSED 2026-08-17** — 8/8 DoD ✅. W2 opens with the pilot build:
restart-Chrome button, per-user unlock + hybrid 2FA, tab persistence,
browser-use re-validation on downloads **+ tab switch (flaked live
2026-08-17)**, denial-path test, tooling image, 2 GB `--memory` cap applied
at deploy. **Viewer canvas fit (2026-08-17 finding):** Chrome UI chrome
(tab bar + toolbar + CfT notice ≈ 141 px, notice has no dismiss button) eats
the 1920×1080 canvas → page footers/pagination fall below the fold (CRM
table pagination unreachable). Workaround live: F11 fullscreen + 90 % zoom.
W2 proper fix: kiosk-mode launch (`--kiosk`) or custom image without the
notice; verify footer visibility on every app.

---

## 8. Incident log

### 2026-08-17 evening — Chrome FATAL after Cloudbrowser restart (resolved)

**Symptom:** viewer Chrome stuck `FATAL` in supervisord ("Exited too quickly"),
n.eko shows no browser. Log signature:
`libprotobuf ERROR ... Can't parse message of type "web_app.WebAppProto"` →
`FATAL:check.cc(376) Check failed: false. NOTREACHED`.

**Root cause (two stacked issues):**
1. **Image drift:** watchtower had updated `ghcr.io/m1k1o/neko/google-chrome:2.9.0`
   to a build shipping **Debian Chrome 133** — the known-broken-CDP version the
   W1 team had already pinned away from (`09-viewer-evaluation.md`; §3). The
   migrated `google-chrome.conf` still pointed at `/usr/bin/google-chrome`
   (→ 133). CfT 128 binary was safe in the profile volume (`cft-chrome-128/`).
2. **Migrated-profile corruption:** even CfT 128 crashed at startup with the
   same `web_app.WebAppProto` FATAL against the migrated `Default/` profile.

**Fixes applied (all live, dev01):**
- `google-chrome.conf` (scripts volume): command → `sh -c 'rm -f …Singleton*;
  exec <profile>/cft-chrome-128/chrome …'` — CfT 128 pinned + proven
  Singleton-cleanup wrapper; `startretries=5` (was 0 → a single quick crash
  previously went FATAL forever).
- Compose (`docker_compose_raw` PATCH): `ulimits: nofile 524288` on **viewer +
  browser** (soft was 1024 — Chrome + 1.2 GB profile exhausted FDs; EMFILE on
  inotify_init).
- Profile: `Default/` rebuilt fresh; persistence-critical data (Cookies, Login
  Data, Local Storage, History, Web Data) restored from `Default.bak-1944`
  (backup kept in the profile volume — never deleted). Chrome healthy since
  (CfT 128, CDP relay verified end-to-end).

**User-relaunch story (W1):** no user action needed for a crash — supervisord
auto-restarts (`autorestart=true`, `startretries=5`); agent can force
`supervisorctl restart google-chrome` from chat. W2 hardening: janitor CDP
watchdog (auto-restart if relay unresponsive) + tooling image (see §9).

## 9. Preinstalled tooling (automation prerequisites)

Inside the **viewer** container (`ghcr.io/m1k1o/neko/google-chrome:2.9.0`),
verified 2026-08-17:

| Tool | In image | Used by |
|---|---|---|
| python3 | ✅ `/usr/bin/python3` | cdp-relay, janitor, window-manager |
| bash / sh | ✅ | wrappers, health checks |
| wget | ✅ | HTTP probes from inside the container |
| supervisorctl | ✅ | process supervision/restart |
| xdg-open | ✅ | (neko UI) |
| **xdotool** | ❌ **missing** | W1 demo save-dialog dismissal (display :99) — native-dialog fallback; **needs install (W2 tooling image)** |
| curl | ❌ missing (wget covers) | — |
| jq | ❌ missing (nice-to-have) | — |
| git | ❌ missing (not needed in container) | — |

Automation itself (playwright/browser-use) runs from the **agent** container
(`/opt/data/cdp-venv`), not from the viewer. Tooling policy for W2: bake
xdotool (+ curl/jq) into a custom image `FROM neko:2.9.0`, or apt-install at
container start via the scripts volume.

---

## 10. Vaultwarden extension preinstalled (Tigo ask → done 2026-08-17)

**Ask:** "is it possible to have Chrome preinstalled with the Vaultwarden
extension?" → **Yes — implemented, verified live.**

### How (force-install + preconfigured URL + pinned toolbar)

1. **Policy file** `bitwarden-policy.json` (scripts volume, canonical in
   `hermes-cloudbrowser/spike/viewer-neko/`):
   ```json
   { "ExtensionSettings": { "nngceckbapebfimnlniiiahkandclblb": {
       "installation_mode": "force_installed",
       "update_url": "https://clients2.google.com/service/update2/crx" } } }
   ```
   (Bitwarden's official Linux/Chrome schema — bitwarden.com/help/browserext-deploy;
   `ExtensionSettings` supersedes `ExtensionInstallForcelist`.)
2. **`policy-init.conf`** supervisord one-shot (`priority=1`, before
   google-chrome): copies the policy from the scripts volume to
   `/etc/opt/chrome_for_testing/policies/managed/` at every container boot,
   then exits. Verified across a full `docker restart` (policy-present, all
   programs RUNNING, extension intact).
3. **`prepare-chrome.sh`** startup wrapper (supervisord `google-chrome`
   program — replaces the old inline mega-command after a nested-quote
   breakage): clears Singleton locks + patches `Preferences` before exec:
   `session.restore_on_startup=1`, `extensions.settings.<bw-id>.
   pin_to_toolbar=true` **and** `extensions.pinned_extensions=[bw-id]`
   (Chrome preserves both on flush, but **CfT 128 ignores them at boot** —
   empirically the toolbar only pins after a real UI action; the wrapper
   keeps pre-writing them as belt-and-braces, W2: bake xdotool into the
   image and run a one-time puzzle→pin click on fresh profiles).
4. **Toolbar pin achieved live** via UI simulation (xdotool, apt-installed
   in the viewer): click extensions puzzle (1771,63) → pin icon on the
   Bitwarden row (1701,225). Chrome's own write persists across restarts
   (verified after `supervisorctl restart`: icon pinned at 1735,62).
5. **Vault URL preconfigured** via `bw-preconfig.py` (agent script, CDP →
   extension service worker): writes the **exact disk shape the extension's
   own UI writes** — `global_environment_environment = {"__json__": true,
   "value": "{\"region\":\"Self-hosted\",\"urls\":{\"base\":\"https://
   secrets.pmo.city\",…nulls}}"}` (+ `global_environment = {"base": …}`).
   ⚠️ A **raw** object under that key is silently ignored (popup stays on
   cloud) — the `__json__` envelope is mandatory. Repo copy is
   URL-parameterized (`VAULT_BASE_URL` / arg); the live value is only on
   the volume/agent side. Verified after full restart: popup shows
   "Accessing: self-hosted", login for the Vaultwarden.

### ⚠️ Discovery: CfT policy path is NOT the neko image's; managed-storage policy unsupported

The neko image bakes `/etc/opt/chrome/policies/managed/policies.json`
(force-installs uBlock Origin + SponsorBlock, blocks `chrome://policy`, etc.)
— **invisible to Chrome for Testing**: CfT 128 reads
`/etc/opt/chrome_for_testing/policies/managed/` (verified by binary strings +
`chrome://policy` reachability + zero extensions in the CfT profile). The
image's uBlock/SponsorBlock therefore do NOT run in the viewer (CfT is the
browser). W2 decision: replicate uBlock/SponsorBlock in the CfT policy if
desired.

**Second CfT limitation (2026-08-17):** the extension's own `managed_schema.
json` (Bitwarden 2026.7.0 supports `environment.base` via `chrome.storage.
managed`) does **not** work under CfT — Chrome logs `nngceckbape… has an
error of type: Unknown policy` and `chrome.storage.managed` stays `{}`.
CfT 128 does not register extension-ID policies (enterprise feature).
Workaround implemented: the URL is preconfigured by writing the extension's
disk state directly (`bw-preconfig.py`, see above).

### Vault URL — preconfigured (no policy key needed)

Bitwarden documents **no server-URL policy key** — but the URL is now
preconfigured via the storage write above: open the extension → it goes
straight to the **vault login for `secrets.pmo.city`** (no Cloud/Self-hosted
chooser, no typing). First unlock is still the user's master password
(per-user unlock + hybrid 2FA is the W2 plan, FR-5/FR-6); the extension's
locked state is the natural entry point.

### Open items (W2)

- **Real "restart Chrome" button** (requested by Tigo): tiny HTTP endpoint
  in the viewer (same pattern as the CDP relay) → `supervisorctl restart
  google-chrome`; surface via a small control page/button and/or agent
  command. neko itself has no app-launch UI (it's a remote-desktop viewer;
  its admin menu only restarts the neko server).
- **Pin bootstrap for fresh profiles**: CfT ignores pre-written pin prefs →
  bake xdotool into the image and run a one-time puzzle→pin click after
  first boot (apt-install in the container is ephemeral).
- Extension state across future profile rebuilds (incident-style `Default/`
  rebuild) — reinstall is automatic via policy; logged-in session is not.
- watchtower image drift (CfT pinned in conf is the mitigation, not a pin on
  the image tag).

---
*Revision: 2026-08-17 — initial audit; updated same day (FR-4 agent control ✅,
relay idle-timeout bug fixed, CfT 128, FR-2 moved to W2 by Tigo, FR-16 numbers
recorded; evening: PMOC_Users gate, migration tunnel-free, crash incident §8,
tooling inventory §9, Vaultwarden extension §10).*
