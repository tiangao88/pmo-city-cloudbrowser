# 64 — Kiosk UX pass: missing Exit outside cloudbrowser pages, 2-tab restore, SSO error tab (2026-08-25)

Status: **ROOT-CAUSED → FIXED → DEPLOYED → LIVE-VERIFIED** (commit `5c64846`)

## Report (Tigo, 2026-08-25, while spike-user held slot-1)

> "Look at the screen in slot 1, it's spike user... there is problems,
> I don't see the exit icon, and only two tabs were restored, and one
> tab has a problem with the SSO."

## Screen state at inspection (slot-1, CDP)

Two tabs restored, both external origins — no kiosk chrome beyond the
extension tab bar:
- `https://secrets.pmo.city/#/login` — Vaultwarden login (email
  pre-filled, "Use single sign-on" visible)
- `https://auth.pmo.city/error` — Authentik generic flow-error page
  ("An error occurred while trying to perform this action...")

## 1) No Exit icon — spec-41 top-bar move left external pages bare

**Root cause:** spec 41 (2026-08-22) moved the Exit affordance OUT of
the tab bar into the **neko top bar** (`ul.menu`, right of the email).
But `ul.menu` only exists on cloudbrowser.dev01.pmo.city pages (title-
proxy injected). Tabs at other origins — Vaultwarden (`secrets.pmo.ci-
ty`), CloudFiles (`cloudfiles.dev01.pmo.city`), SSO (`auth.pmo.city`),
any external site — have no top bar, and the extension tab bar (v1.12.0)
no longer hosted Exit (its `#exitpop` + `SELF_RELEASE → /release` flow
survived, only the button was removed). The user's whole kiosk view was
external tabs → **no release affordance anywhere** (the "power" icon is
"Relaunch Chrome", a Chrome restart, NOT a session release).

**Fix (content.js v1.13.0, spec 64):** universal Exit **fallback**. The
tab bar re-hosts the Exit button (right end, door-glyph + "Exit session
(release slot)"), shown **only when no neko top bar is present**
(`document.querySelector("ul.menu")` false), re-checked on a 2 s poll.
On cloudbrowser pages the spec-41 top-bar Exit stays the primary and the
bar button stays hidden (no duplication, queue page still excluded via
the top bar's `/fleet/my-status` gate). Same confirm popup →
`SELF_RELEASE` → restart-api `/release` (slot-user-derived, spec-32/41
semantics unchanged). Versions bumped 1.12.0 → 1.13.0 (content.js
VERSION, background.js EXT_VERSION, manifest).

**Deploy:** 4 files to the shared scripts volume (`restart-api.py`,
`tabbar-extension/{content.js,manifest.json,background.js}`), md5
verified. Extension reloaded in the live Chrome via
`chrome.runtime.reload()` evaluated in the service worker (CDP raw
websocket) — invisible to the active session.
**Live-verified:** on the user's live tabs (`pmo.city`,
`agenticpmo.org`) the bar button `#exit` exists, visible, correct title;
`hasUlMenu=false` → shown. Harness 109/109, py_compile clean.

## 2) "Only two tabs restored" — faithful restore, snapshot had exactly 2

**Not a restore bug.** Archived snapshot at session end:
```json
{"ts": 1787656153, "urls": ["https://secrets.pmo.city/#/login",
                            "https://auth.pmo.city/error"]}
```
The watchdog persisted exactly the tabs that were open (max 3 is a
**cap**, not a target; homepage `pmo.city` is never persisted — zero-
tabs fallback rule). Both URLs were restored 1:1. The session page
(cloudbrowser root) is not a tab to restore — re-entry re-lands on it
via the router's active-reload 302.

## 3) "One tab has a problem with the SSO" — Authentik dead-end persisted

**What the tab is:** `auth.pmo.city/error` = Authentik's generic
flow-error page. It was captured into the snapshot during the previous
session and **resurrected on every wake** — an SSO flow already failed,
and the error URL cannot succeed on restore (a fresh SSO requires a new
flow URL).

**Underlying cause (Authentik side, evidence):** the shared Authentik
server log (2026-08-25, 09:59→11:04) shows recurring
`f(plan_inst): binding failed re-evaluation` on flow
`08f98da3-…` / stage-binding #20, `auth_via: unauthenticated`, host
`auth.aikumi.app` — every kiosk SSO attempt without an existing
Authentik session hits this stage-binding policy failure. Since spec 52
intentionally strips identity cookies each archive/restore (fresh SSO
per session), **every session** is "unauthenticated" and thus every
vault-SSO attempt lands on the error page. This is an Authentik
flow/stage-binding configuration problem (binding #20's policy cannot
re-evaluate for anonymous users) — **administration of the shared IdP
was left for Tigo/ops; not touched from the kiosk side.**

**Fix (kiosk side, deployed):** dead-end SSO error pages are never
persisted nor restored:
- `restart-api.py` `_is_sso_error()` — host in
  {auth.pmo.city, auth.aikumi.app} AND path `/error` (query-tolerant).
- `snapshot_tabs()`: excluded at capture.
- richer-keep comparison + `load_snapshot()`: dead-ends filtered from
  the existing snapshot too, so a previously persisted error page is
  purged at the next wake/restore.
- 7/7 unit cases pass; **live snapshot 50 s after deploy already free
  of `auth.pmo.city/error`**.

## Files

- `scripts/tabbar-extension/content.js` v1.13.0 (bar Exit fallback)
- `scripts/tabbar-extension/manifest.json` → 1.13.0
- `scripts/tabbar-extension/background.js` EXT_VERSION → 1.13.0
- `scripts/restart-api.py` (spec-64 SSO dead-end filter)
- `specs/64-kiosk-exit-tabs-sso.md`

## Open items

- Authentik flow `08f98da3-6332-48b6-977b-49856552a444`, stage-binding
  #20 policy re-evaluation failure for unauthenticated users — needs a
  decision: fix the binding policy, or retire the vault SSO button as a
  kiosk path (D3 OIDC server-side flow is the sanctioned route).
- `error.html` (O6 chrome-error replacement page) has its own bar copy
  — could gain the same Exit fallback later (W4 nicety, not required:
  error pages are transient).
## Follow-up: Authentik investigation (2026-08-25) — warning is benign

Verdict: **nothing to fix in Authentik.** The recurring log line is the
stock blueprint policy working as designed.

Decoded chain (read-only DB investigation of the shared IdP):
- Flow `08f98da3-6332-48b6-977b-49856552a444` = **"Aikumi Connect!"**
  (`default-authentication-flow`, designation=authentication) = the
  authentication flow of **Provider for PMOC Vaultwarden** (provider pk
  35; authorization flow = `0c41f060…` "Authorize Application").
- Binding **#20 = order 20** (source: `FlowStageBinding.__str__` →
  `f"Flow-stage binding #{self.order} …"`) = the **Password Stage**
  (`02f61eb1-…`), which carries Authentik's **stock** expression policy
  `default-authentication-flow-password-stage`:
  `return not hasattr(flow_plan.context.get("pending_user"), "backend")`
- The warning fires exactly when that policy returns False → the
  password stage is legitimately **skipped** (pending user already has
  an auth backend). Correlation: the warning timestamps
  (10:13:53, 10:18:24, 10:33:52, 10:56:21, 10:58:52, 11:04:57) match 1:1
  the kiosk's successful `authorize_application` events in
  `authentik_events_event`; event log shows **zero** `auth_flow_error`
  rows in the inspected window. SSO from the kiosk works.

The kiosk `auth.pmo.city/error` tab was a **stale restored snapshot
artifact** (an older failed attempt, e.g., the 10:00:24 "revoked
refresh token was used" suspicion by the Vaultwarden client), not a
live flow failure → the spec-64 filter (never persist/restore SSO
dead-ends) is the complete fix.

If the log line is ever wanted silenced (cosmetic-only, not
recommended): Flows → "Aikumi Connect!" → Stage bindings → the
Password Stage entry (order 20) → uncheck **Re-evaluate policies** →
save. Trade-off: stage re-evaluations mid-flow (e.g. picking an SSO
source at identification) stop hiding the password prompt reactively.

## v1.13.1 — Release confirm popup was off-screen (2026-08-25)

Tigo: "I clicked release session, it doesn't work." — the confirm popup
opened **below the viewport**: `openExitPop()` anchored the popup below
the button (`rect.bottom + 4`), which is right for the neko TOP bar but
wrong for the tab-bar fallback at the BOTTOM of the page (hidden below
720px; DOM showed `exitpop.hidden=false` + `popTop≈721`).

Fix (content.js v1.13.1): popup anchors by bar position — `pos ===
"bottom"` → open ABOVE the bar (`rect.top - h - 4`), else below.
Versions bumped (manifest, VERSION, EXT_VERSION → 1.13.1), volume
deployed (md5 verified), extension reloaded via SW + page reloaded.
Live-verified on the vault tab: popup 611.5–693.9 px, fully visible,
Cancel closes. Release chain (SELF_RELEASE → restart-api /release) was
never reached by the user because the confirm was invisible — now
reachable.

## User validation (2026-08-25, Tigo)

- **Release works** — exercised live on spike-user's session (and on his
  own montigaud session): router log shows the full cycle repeated
  (`released spike-user → archived reason=released → offer montigaud →
  taken → released → offer spike-user → taken`). Slot freed, queue
  head offered, session archived per-user.
- **"Only one tab restored" = accepted** ("that's perfect"): the
  snapshot held 2 URLs at session end — the Vaultwarden login + the
  `auth.pmo.city/error` dead-end; with SSO dead-ends now filtered,
  1 valid tab restores. Expected behavior, not a regression.
- Spec 64 status → **DONE, user-validated**.
