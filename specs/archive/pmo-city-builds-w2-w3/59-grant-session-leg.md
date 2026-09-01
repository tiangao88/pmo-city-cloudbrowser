# 59 — Grant session-token leg: "Shared" means usable (2026-08-25)

> **Refactor clarification — 2026-09-01:** The two-leg grant remains a
> compatibility baseline, but runtime consumption belongs behind the broker
> boundary. `grant-sync.py` and direct slot-side decryption are not evidence of
> the final architecture. See `85-credential-broker-prd.md` and
> `87-broker-security-model.md`.

Status: **IMPLEMENTED → DEPLOYED → LIVE-VERIFIED** (commit `34c09d0`)

## Problem (Tigo)

> "Why do you need me to unlock Vaultwarden if /connect is Shared?"

The green Shared pill meant only "the vault decryption key is captured".
The broker could not authenticate to the vault API, so the user was asked
to unlock again — a false green. Tigo's directive (2026-08-25):

> "implement the missing session-token leg and retain green Shared only
> when both components are usable"

## Design (Locked)

The grant store now holds TWO wrapped legs (both AES-256-GCM under the
per-user K_user, `granthub.py`):

| leg | content | captured when |
|---|---|---|
| `wrapped_key` | the user's 64-byte vault key (decrypts items) | vault unlock |
| `wrapped_session` | a vault **refresh token** (authenticates) | SSO round-trip |

`/connect/status` now reports `shared` (key leg), `session` (token leg)
and **`usable` = both**. Every consumer (top-bar pill, landing pill,
`/connect` card, live-flip JS) renders green **only on `usable`** —
a key-only grant stays red until the session leg lands.

## Why not the `stateService` accessor (spec 57 Leg B)

Probed live at `#/lock` (2026-08-25): `window.bitwardenContainerService`
exposes only `encryptService` + `keyService` — **no stateService** on
this build, so `getAccessToken()` is unreachable from the page. Replaced
by a deterministic **network capture**:

- The SSO round-trip the broker already drives ends with the vault SPA
  POSTing `/identity/connect/token` (grant_type=authorization_code);
  the response body carries `refresh_token`.
- `HOOK_JS` (sso-broker.py) wraps `fetch` + `XMLHttpRequest` on the
  vault origin, copies that token into a window global; installed via
  `Page.addScriptToEvaluateOnNewDocument` (survives the auth redirects)
  + once on the current document. Value read once, wrapped, never
  logged.

## Changes

- **granthub.py**: `wrap_bytes()`, `save_grant(wrapped_session=)`,
  `add_session()` (session-only upgrade), `load_kuser()`,
  `unwrap_session()`, `status()` → `{shared, session, usable, ...}`.
- **router.py**: `/connect/grant` accepts `key` and/or `session`
  (session-only = upgrade of an existing key grant); `_shared_state`
  (both store and status-URL paths) + landing `#ghPill` + `/connect`
  card all gate on `usable`.
- **title-proxy.py**: server-side pill + live-flip JS gate on `usable`.
- **sso-broker.py**: `HOOK_JS`/`COLLECT_JS`, `install_token_hook()`,
  `collect_refresh_token()`, `post_session()`, `capture_session_leg()`
  (key-grant-present path), and the **rotation watcher** — while a vault
  tab is present, re-collect + re-post any NEW refresh token every 30 s
  (Vaultwarden rotates refresh tokens on every use; the SPA's own
  refresh would otherwise silently kill the stored leg).
- **grant-sync.py** (router container, `/app`): consumption proof —
  unwrap both legs → `POST /identity/connect/token`
  (grant_type=refresh_token, client web) → `GET /api/sync` (flat body)
  → decrypt the target item (AesCbc256_HmacSha256_B64, encType 2:
  HMAC-SHA256(macKey, iv‖ct) then AES-CBC PKCS7 via vendored pyaes) →
  **persists the ROTATED refresh token back** into the grant store.
  Prints status/lengths only (FR-9).
- **test-granthub.py**: 34/34 — key-only grant `usable:false`,
  session-only upgrade 400 without a grant, upgrade → `usable:true`,
  no plaintext token in grant.json, combined grant, unwrap_session
  roundtrip + revoke refusal, pill gating for key-only vs usable.

## Live evidence (slot-1, spike-user@aikumi.pro)

1. `stateService` probe → `{"ok":false,"why":"no-stateService"}`
   (surface: only encryptService/keyService).
2. **Tigo completed the SSO login manually in the kiosk** — the armed
   hook captured the refresh token from that round-trip
   (`session upgrade POST OK — grant usable`, 09:59:42). Honest note:
   the broker's own `fill_and_submit` did not drive THIS login (proven
   in earlier runs, spec 57); what is proven autonomous here is the
   capture → store → gate chain.
3. **Rotation watcher** caught the SPA's own token refresh and re-posted
   (`rotation watcher: stored session updated`, 10:02:15) — the stored
   leg survives rotation without any user action.
4. **Consumption** (`grant-sync.py spike-user@aikumi.pro`):
   ```
   grant: key OK (64B), session leg OK
   token mint OK: access_token present, expires_in=1800s
   sync OK: 2 cipher(s), profile=spike-user@aikumi.pro
   rotated refresh token persisted back to grant store
   item: Powermail (id 1d1dcee2-f6bc-4cdd-98a0-e911e2dd9a72)
   username: pmoc-spike-user
   password: DECRYPTED OK, length=14
   READ-PATH VERIFIED: broker can mint a session and decrypt vault
   items from the stored grant alone.
   ```
5. `/connect/status` → `{ok, shared:true, session:true, usable:true,
   revoked:false}` — pill green on all surfaces.

## Semantics now (locked)

- **Green Shared = the broker can read your vault items autonomously.**
  No user unlock, no master password, revocation still bites
  (revoke → `k_user.bin` deleted → both unwraps fail → red).
- Key-only grant renders red ("Not Shared") until the session leg is
  captured — never a false green.

## Files / deploy

- `scripts/{granthub,router,title-proxy,sso-broker,grant-sync,test-granthub}.py`
- Deployed to `okixw2fxnwn1lakxvxajodww_scripts` volume; router
  restarted; slot-1 sso-broker + title-proxy restarted. Verified live.
- Follow-up: the actual PowerMail site fill (`go.powermail.fr`
  Roundcube) can now run with zero user unlock — the credential is
  readable from the grant alone; run on the next slot window.
