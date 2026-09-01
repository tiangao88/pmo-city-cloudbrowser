# W2 Autonomy Register — what the agent does without Tigo

> **Approved 2026-08-17 (Tigo).** Companion to `20-w2-dod.md` (official W2
> DoD). This register states, per W2 DoD item, what the agent executes
> **autonomously**, what needs Tigo, and what Tigo executes himself.
> Legend: **A** = agent executes alone (no Tigo needed) ·
> **P** = agent + Tigo (agent builds, Tigo supplies/validates) ·
> **T** = Tigo executes (agent supports).
> Standing grants (bottom of this doc) are in force unless overridden here.

---

## 1. W2 DoD execution matrix

| DoD | Item | Mode | Agent does alone | Needs from Tigo |
|---|---|---|---|---|
| D1 | Per-user browsers + unlock | **P** | Build the multi-instance wiring (Coolify clone + per-user env, naming "Browser — \<name\>", URL subpath) once the approach is confirmed | Confirm wiring approach (open pt 3); provide pilot user names + group memberships |
| D2 | Hybrid 2FA | **P** | Implement TOTP-if-present + chat-prompt paths in the broker flow; create Vaultwarden test items (grant G2 below) | Validate the chat-prompt leg as the human (type a code when asked) |
| D3 | Broker OIDC session flow | **P** | Implement broker-side OIDC session flow against the test client | Provide/configure the IdP (Aikumi Connect/Authentik) test OIDC client + test user |
| D4 | Restart-Chrome button | **A** | HTTP endpoint in viewer (CDP-relay pattern) → `supervisorctl restart`; janitor CDP watchdog; verify <30 s with profile intact | — (notify before live-session restarts) |
| D5 | Tab persistence | **A** | Implement `stopwaitsecs=30` / tab-snapshot mechanism; verify across container recreate on dev | — (dev viewer restarts authorized; sequence with live CRM session) |
| D6 | browser-use re-validation | **A** | Re-validate tab switch + downloads on the real viewer; record result; keep raw-CDP fallback documented | — (unless fallback decision needed → open pt 4) |
| D7 | Canvas fit / kiosk | **A** | Kiosk-mode launch (chrome.conf), CfT-notice solution, footer-visibility checks on pilot apps | — (dev restarts authorized; sequence with live session) |
| D8 | In-viewer file list | **A** | Build the viewer-side file list (server.py extension in scripts volume), refresh-on-download, open/retrieve; keep chat retrieval + EICAR re-test | — (UX approach proposed before finalizing — Tigo reviews per design convention) |
| D9 | Capacity limits | **A** | Apply 2 GB `--memory` cap + `MAX_RUNNING_BROWSERS` on dev01; saturation-message test; soak tracking | — (deploy of cloud-browser dev service pre-authorized, grant G1; timing notice for live session) |
| D10 | Denial path | **P** | Prepare/verify the 403 path server-side; run the member regression | A non-`PMOC_Users` account to click the link (Tigo-side) |
| D11 | Tooling image + drift pin | **A** (2026-08-18) | **start-script apt chosen** (supervisord one-shot `tooling-init`, priority 0 — DoD explicitly allows it, so A4's registry gate is **bypassed, no image to build**); drift-pin strategy = image tag pin + CfT binary in profile volume + launch path in scripts volume; verified through the D9 container recreate (CfT 128.0.6613.137, tools back) | ~~A4 (registry access)~~ → resolved: not needed |
| D12 | Viewer hygiene | **A** | Translate-off policy/profile; janitor closes stale extension popups | — |
| D13 | Screen-follow | **P** | Research + prototype (neko v3 feature or custom bridge); wire after D7 | Decide approach (open pt 6) and sequencing vs kiosk |
| D14 | SME workflow validation | **P** | Drive the CRM workflows on command (browse → qualify → contact), capture evidence, record gaps | Execute/validate as SME; sign the DoD (Lee re-validates later) |

**Summary: 8 items fully autonomous (D4, D5, D6, D7, D8, D9, D11, D12) · 6 items
partial (D1, D2, D3, D10, D13, D14) · 0 items Tigo-only.**

---

## 2. Standing grants (in force — from W1, not re-negotiated)

- **G1 — Deploys:** first + subsequent Coolify deploys of the **cloud-browser
  service in PMO City dev** are authorized — no per-deploy approval needed
  (granted 2026-08-16; recorded in `08-roadmap.md` W1 autonomy section).
- **G2 — Vaultwarden test items:** the agent may create broker-spike test
  items in Vaultwarden (W1 one-time grant; **extended to W2** for D2/D3 test
  items — user-level items in the share-vault test collection only).
- **G3 — Agent-side cloud-browser changes:** scripts volume (chrome.conf,
  cdp-relay, janitor, window-manager, server.py, policies) + viewer container
  files are agent-owned; changes may be applied directly (dev only).
- **G4 — SSH mother01 (dev box):** agent root access for cloud-browser
  operations on dev01.
- **G5 — Repos:** commits/pushes to `pmo-city-builds` + `hermes-cloudbrowser`
  follow the standing git conventions (identity, fetch+rebase, staged paths,
  template-only rules for the template repo).

---

## 3. Boundaries — NEVER without Tigo (unchanged)

- **Prod:** nothing on production servers, any service — read-only at most.
- **Old W1 stack** (`cloudbrowser-ism3def5kz88edlerxakcun1`): Tigo destroys
  it himself; the agent never touches it.
- **Hermes agent container(s):** Tigo changes/redeploys personally.
- **Deploys of any service other than the cloud-browser dev service.**
- **Business-data writes** in the CRM or any real app: no status changes, no
  "Confirmer projet", no notes/edits — until Tigo explicitly approves a
  write-action test on a chosen record.
- **Secrets:** never echoed/logged/exposed; env-file refs or Vaultwarden
  only (credential hygiene rule).
- **Scope creep:** anything outside W2 DoD + this register → ask first.

---

## 4. New asks for W2 (what the agent needs to go full-speed)

| # | Ask | Needed for | Who |
|---|---|---|---|
| A1 | Confirm multi-user wiring approach (per-user link → instance) | D1 | Tigo (decision, open pt 3 of 20-w2-dod) |
| A2 | IdP test OIDC client + test user on Aikumi Connect/Authentik | D3 | Tigo or admin |
| A3 | Non-`PMOC_Users` test account for the denial-path click | D10 | Tigo |
| A4 | Dev image-registry access | D11 | ~~Tigo~~ → **resolved 2026-08-18**: start-script apt chosen (DoD-allowed) → no image, no registry needed |
| A5 | Notify (not approval) before live-session restarts (D5/D7/D9) | sequencing | Agent → Tigo heads-up |
| A6 | Browser-use fallback policy if tab switch can't stabilize | D6 | Tigo (decision, open pt 4) |
| A7 | Screen-follow approach + kiosk sequencing | D13 | Tigo (decision, open pt 6) |

---

## 5. Decisions taken (2026-08-21) — cloud-browser fleet sizing

- **Finding:** `--kiosk` + `--restore-last-session` (restore_on_startup=1)
  restored the previous session's window geometry (945×1060 on a
  1920×1080 desktop) → small browser window + black void on fleet slots.
  Screen itself (X/neko) is correct at 1920×1080 — this is a Chrome
  window-geometry issue, not a screensize variable issue.
- **Decision (Tigo, 2026-08-21):** keep the **tabbar Relaunch Chrome
  restore button** as the pilot workaround (reloads the page at the right
  size; users should know it) — **no disruptive Chrome restart now.**
- **Staged fix (applies at next natural Chrome restart):**
  - `slot-prepare-chrome.sh`: drop `--restore-last-session`, add
    `--window-size=1920,1080`, Preferences `restore_on_startup=1 → 5`
    (fresh start; cmdline URL still opens pmo.city).
  - Updated in repo (canonical `26-s7-fleet-slot-prepare-chrome.sh`) +
    live scripts volume (sha-identical), **not yet applied** (no restart).

---

## 6. Decisions taken (2026-08-21) — tabbar: homepage, Home/Plus, tab limit

Full spec: `27-tabbar-home-limit.md` (approved, implementation holds for "go").

- **Bug (verified in code):** every slot start / Relaunch Chrome adds a
  homepage tab — launch URL `https://pmo.city` in `slot-prepare-chrome.sh`
  + D5 restore re-opening the snapshot (which contains the homepage) →
  tabs pile up.
- **S1:** remove the launch URL; homepage opens **only when zero real
  tabs** (restart-api boot/restore path decides; snapshot exists → restore
  without homepage).
- **S2:** 🏠 Home icon **between Relaunch and Back** → opens `HOME_URL` tab.
- **S3:** ＋ icon **after Reload** → inline URL popover → new tab (http(s)
  only, auto-`https://`).
- **S4:** tab limit = **`TAB_LIMIT` env, default 3**; count = real http(s)
  tabs; Home/Plus **disabled+tooltip** at limit; **D5 restore capped**.
- **S5:** compose vars **`HOME_URL`** (default https://pmo.city) +
  **`TAB_LIMIT`** (default 3), fleet **and** viewer.
- **Plumbing:** MV3 can't read env → restart-api gains `GET /config`
  `{homeUrl, tabLimit}`; extension fetches at startup (127.0.0.1:9230
  permission already present), caches, falls back to defaults.
- **Deploy:** needs one Chrome restart per slot (new extension) — the
  staged window-size fix lands in the same restart; Tigo's go required.
