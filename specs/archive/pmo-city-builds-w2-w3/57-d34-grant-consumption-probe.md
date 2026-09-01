# 57 — D3.4 grant-consumption probe & design (2026-08-25)

Status: probe ✅ done (evidence below) · consumption fix ⏳ next (2 items)

## Question (Tigo, 2026-08-25)

> "Why do we need to open the vault again if the dedicated authentication
> token is already shared? If /connect is already shared, isn't that
> sufficient? Why do we need to open Vaultwarden again?"

Answer: **the shared grant IS sufficient by design — the gap is that the
grant today stores only the decryption key, and the consumption leg
(D3.4) that turns it into a full session is not yet implemented.** The
user should never need to re-open the vault after the grant exists.

## What was proven live (slot-1, spike-user@aikumi.pro)

1. **Grant unwrap — ✅ working.** In-slot (Python 3.9), deterministic:
   read `/data/sessions/<user>/grant/{grant.json,k_user.bin}`, AES-GCM
   decrypt (gcm.py), recovered the user's **64-byte vault key** (32B enc
   + 32B MAC). No master password anywhere. (Note: `granthub.py` uses
   `bytes | None` annotations — 3.10+ syntax — which the slot's Python
   3.9 cannot import; the probe inlines the same unwrap logic with
   `gcm.gcm_decrypt` directly.)
2. **SSO round-trip — ✅ working.** Kiosk vault tab at `#/login` → clicked
   "Use single sign-on" → filled `spike-user@aikumi.pro` → **sso-broker
   auto-filled the Authentik identification stage** (shared SSO creds) →
   Vaultwarden completed the OIDC code exchange → landed at `#/lock`
   (authenticated session state, data still client-side locked).
3. **Token probe at `#/lock` — ❌ found nothing in STORAGE** (21 candidates
   from sessionStorage/localStorage + shallow stateService string fields
   rejected by `/api/accounts/profile`). **Root cause: the probe looked in
   the wrong place.** The Bitwarden web vault keeps its API tokens in the
   SPA's **in-memory `stateService`** (`getAccessToken(userId)` /
   `getRefreshToken(userId)` accessors), not in web storage. The SSO
   session token was present in memory the whole time.

## Root cause of the "re-open the vault" impression

- The grant = the user's **decryption key**. A key decrypts; it does not
  authenticate. Vaultwarden's API (`/api/sync`) requires an **API session
  token** (Authorization: Bearer) to return the encrypted blobs.
- Session tokens are minted only by: (a) master password + KDF hash —
  **never available to the broker by design** (FR-9, spec 34 §6); (b) an
  SSO login — **the broker can do this autonomously** (proven above);
  (c) a refresh token from a prior login.
- **Key insight:** `#/lock` is a **client-side** state — the API returns
  the encrypted items to *any* authenticated session; the page just can't
  decrypt them without the user key. The grant provides exactly that key.
  Therefore: **SSO session + unwrapped grant key = full read capability,
  no master password, no unlock screen.**

## Fix design — D3.4 completion (two legs)

**Leg B (immediate, uses today's proven pieces):**
1. At `#/lock` after the broker's SSO round-trip, read the access token
   via `stateService.getAccessToken(activeUserId)` (verify accessor on a
   live session — next step).
2. `GET /api/sync` with that token → ciphertext list.
3. Decrypt names/passwords in-process with the unwrapped grant key
   (AES-CBC-HMAC-SHA256; `encryptService.decryptString` semantics proven
   in the step-4 spike).
4. Fill the target site (PowerMail Roundcube form) via CDP; status only.
→ User never opens the vault; revocation still bites (`k_user.bin` delete
   → unwrap fails → chain dead).

**Leg A (long-lived, spec 34 Phase 3 — "grant once, self-refreshes
forever"):**
1. At grant-capture time (GH.4), capture the **refresh token** alongside
   the user key via `stateService.getRefreshToken(userId)`, wrap it with
   `K_user`, store in the same per-user grant folder.
2. Broker server-side: unwrap → `POST /identity/connect/token`
   `grant_type=refresh_token` → fresh access token → `/api/sync` →
   decrypt → fill. Refresh tokens are long-lived in Vaultwarden
   (default 6 months, configurable); revocation kills them immediately.

## Open / verify items

- [ ] Verify `stateService.getAccessToken()` / `getRefreshToken()`
      accessors on a live slot session (next offer).
- [ ] Decide Leg A capture extension (wrap refresh token at GH.4 capture).
- [ ] Re-run the PowerMail e2e with Leg B on the next spike-user session.

## Evidence (live, 2026-08-24/25)

- `STATUS: grant unwrapped OK (key present, 64B)` — in-slot unwrap.
- `SSO: clicked` / `SSO ROUND-TRIP: back` — broker completed Authentik.
- `VAULT: #/lock|no-vault-ui` after SSO — session established, data locked
  client-side only.
- `STATUS: no usable vault session token (tried 21 candidates)` — storage
  probe; stateService accessor not yet tried (slot expired before retry).

## Tooling

- `/opt/data/cb-pm-grant.py` — full Leg-B flow (unwrap → SSO → token →
  sync → decrypt → fill → status); runs in-slot via `docker exec`.
- `/opt/data/cb-pm-tokprobe.py` — storage + shallow-state probe (the
  gap-finder; must be extended with the stateService accessors).
- Slot Python 3.9 pitfall: inline `granthub.unwrap` via `gcm.py` rather
  than importing granthub.py (3.10+ type syntax).
