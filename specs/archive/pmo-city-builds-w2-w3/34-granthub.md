# GrantHub — Per-user revocable vault grant (34)

> **Refactor clarification — 2026-09-01:** GrantHub remains the user-consent
> and revocation surface. The Credential Broker is the only runtime consumer
> of credential-fetch capability. The exact wrapped-material custody split is
> intentionally reopened for the refactor; no agent or ordinary slot runtime
> may consume or decrypt it directly. See `85-credential-broker-prd.md`,
> `86-product-boundaries.md`, and `87-broker-security-model.md`.

Status: **VALIDATED (Tigo, 2026-08-22)** · added 2026-08-21 (Tigo) · links: FR-9, FR-10 (02-functional-requirements.md), D15 SSO (23-d15-sso.md)

> **Validated 2026-08-22 (Tigo) with 4 adjustments** (all applied below):
> (1) **two separate buttons** — 🔒 **Secrets** is one button, unchanged,
> links to Vaultwarden at `https://secrets.pmo.city`; **🔗 Not Shared** is
> a *second* button that opens GrantHub `/connect`. (2) Step-4 spike was
> verified 2026-08-21 — proof is in GitHub (§6 open question 3); the ⚠
> Unverified marker is removed. (3) After a successful grant the **Not
> Shared** button transforms ("flips") into **🔗 Shared**. (4) Clicking
> **🔗 Shared** opens a popup to confirm **revocation** of the grant (on
> confirm, the button reverts to **🔗 Not Shared**).
>
> **Colors (Tigo, 2026-08-22):** the **🔗 Not Shared** button is written
> in **red**; the **🔗 Shared** button is written in **green**. State and
> color both come from the server-side grant state on render.
>
> **Capture channel (CONFIRMED 2026-08-22, Tigo):** the step-3/4 vault
> login + key read happens **inside the slot's embedded Chrome** — the
> user's browser in the W2 pilot. The broker (sso-broker, ported to slots
> in D3) injects the capture script via CDP on the `secrets.pmo.city`
> page and POSTs the wrapped key to the GrantHub API. Parent-browser
> wording below is W1-era phrasing.
>
> **Note (verified 2026-08-22, live bar screenshot):** both buttons
> **already exist in the interface** — current tab bar = `CloudFiles ⏐ 🔒
> Secrets ⏐ 🔗 Not Shared ⏐ <email>`. GrantHub implementation therefore
> **wires these existing controls**, it does not create new ones (🔒
> Secrets already → `secrets.pmo.city`; 🔗 Not Shared gains the `/connect`
> link + Shared state + revoke popup).

> **Standalone spec for GrantHub** — the per-user revocable grant app for
> Vaultwarden access. This is the **only** component that ever touches a
> user's vault key. Derived from the 2026-08-21 design discussion
> (Tigo + agent), following the verified live proof that a fresh session
> in a **separate state folder** decrypts without the master password.

## 1. Problem

The cloud-browser broker needs to read **per-user** Vaultwarden items
(site credentials, 2FA seeds) to perform logins on the user's behalf
(FR-9, FR-10). Two naive designs fail:

- **Reuse the gateway's own Vaultwarden session** — wrong vault: that's the
  *gateway's* account (`webmaster@pmo.city`), not the user's. The user's
  vault is a different account.
- **Store each user's master password centrally** — a central honeypot; a
  single compromise reads every user's vault; master-password hygiene is
  destroyed (a shared/stored master password is a compromised one); and the
  user must *give us* their master password (hard trust sell, breaks the
  "master password never enters LLM context" invariant).

**Decision (2026-08-21, Tigo):** per-user **revocable grant** — the
security-acceptable middle path. The user grants access **once** via a
grant app; the broker holds a **wrapped user key** that is **valid until
revoked** and can be killed **instantly**; the broker **auto-re-mints**
short-lived sessions from it, so the user never re-grants.

## 2. The new component: GrantHub

| | |
|---|---|
| **Name** | GrantHub |
| **URL** | `https://cloudbrowser.dev01.pmo.city/connect` (same origin as the cloud-browser broker) |
| **Type** | small web app — **new code** (page + API + per-user key store) |
| **SSO** | **TinyAuth only** (the PMO City SSO; may proxy to client IdP or basic auth — GrantHub talks only to TinyAuth) |
| **Role** | the **only** component that ever touches a user vault key |

GrantHub lives on the cloud-browser domain because we control **all**
applications under it: existing TinyAuth gate, CORS, TLS. No new domain,
no new SSO.

## 3. The flow — step by step

### Phase 1 — User setup (one-time, ~2 min)

1. The tab bar shows two distinct controls (the spec-37 top-bar block
   `🔒 Secrets · 🔗 Not Shared`):
   - **🔒 Secrets** → opens **Vaultwarden** at `https://secrets.pmo.city`
     (unchanged — direct vault access in the parent browser).
   - **🔗 Not Shared** → opens **GrantHub**
     (`cloudbrowser.dev01.pmo.city/connect`) in the user's **own browser**
     (the parent browser — same human-door behavior as the existing
     Secrets button, per 23-d15-sso.md).
2. GrantHub → **"Login with SSO"** → **TinyAuth** (the PMO City SSO).
   TinyAuth authenticates the user — it may proxy to the client's own IdP
   if configured, or use basic auth; GrantHub only ever talks to TinyAuth.
3. GrantHub **redirects to the Vaultwarden login page** (`secrets.pmo.city`).
   The user logs in — **directly with their Vaultwarden master password**,
   or via **an SSO choice if the login page offers one** (TinyAuth or the
   client's IdP — we don't care which). **After any SSO choice, they still
   enter the master password** (Vaultwarden requires it to derive the user
   key). Their vault unlocks **in their browser**; the page's JS now holds
   the **user key in memory**.
4. GrantHub's JS reads the user key from the vault app's in-memory state and
   sends it **directly to GrantHub's API over TLS** (never through the LLM,
   never logged).

> **✅ VERIFIED (the spike, 2026-08-21):** step 4 — reading the user key
> from the vault app's in-memory JS state on our deployed Vaultwarden
> version. Proven live (bot `webmaster@pmo.city`): the full functional
> user key is readable via injected JS and decrypts real vault data
> byte-for-byte matching the `bw` CLI. Full proof in §6 open question 3.
>
> **After a successful grant** (GrantHub API returns `granted`), the
> tab-bar **🔗 Not Shared** button transforms into **🔗 Shared**. The state
> is stored server-side per user; the tab bar reads it on render (no page
> reload needed on the parent side).

### Phase 2 — Storage (no honeypot, per-user folder)

5. GrantHub API **wraps the user key** with a per-user random wrapping key
   `K_user`, stores only:

   ```
   { user, wrapped_key, scope = "PMO City vault", issued_at, revoked = false }
   ```

   in a **per-user row**. The master password is **never stored**.

**Key-wrap custody (decision 2026-08-21, Tigo):** we already have a
**per-user folder** (the browser's profile volume — per D15, the browser's
identity *is* the human). So **everything for user U lives in U's folder**:
the wrapped key, the wrapping key `K_user`, and the broker's isolated state
(Phase 3). No central key store, no cross-user coupling — one place per
user, simple. This is what the "no honeypot" posture means concretely:
compromise of one user's folder = one user's vault, nothing else.

### Phase 3 — Broker consumption (proved live)

6. Broker wants vault access for user U → calls GrantHub → gets the
   `K_user`-wrapped key → **unwraps** → **mints a fresh Vaultwarden session
   in an isolated per-user state folder** (the verified separate-folder
   pattern: folder + session → `status: "unlocked"` → plaintext, no
   master-password prompt) → decrypts.

### Phase 4 — Revocation

7. **User revoke:** clicking **🔗 Shared** in the tab bar opens a
   **confirmation popup** ("Revoke this grant?") → confirm → user is back
   on GrantHub → **one click: revoke** → the wrapped key is marked
   `revoked` → unwrap fails → re-mint dies → broker can no longer decrypt.
   The button reverts to **🔗 Not Shared**. **No master-password change
   needed.**
8. **Admin kill switch (decision 2026-08-21, Tigo — safety):** an admin
   surface can **revoke every grant given by every user** (kill-all). This
   is the emergency/safety control: e.g. incident, departed user, suspected
   compromise. One action, all grants dead.

## 4. Key lifecycle (the critical design)

Two distinct expirations — this is the heart of the design:

| Layer | Lifetime | Mechanism |
|---|---|---|
| **Wrapped key** (the grant) | **Valid until revoked** — no expiry (decision 2026-08-21) | Revocation is the kill-switch |
| **Broker session** (runtime access) | **Short-lived** (hours) | **Auto-re-minted** from the wrapped key on demand |

- The user grants **once**; the broker **self-refreshes** sessions forever
  after (auto re-mint: unwrap → fresh session in the isolated folder →
  use → expire → repeat). **No periodic user re-grant.**
- **Revocation must bite:** GrantHub flags/deletes the wrapped key so
  unwrap fails and re-mint dies. A *previously minted* session lives out
  its short life (inherent to sessions) — short lifetime = small window.
- This is the right trade-off: one grant, full autonomy, instant kill.

## 5. Security posture

| | Central master-password store | **GrantHub (this design)** |
|---|---|---|
| Master password stored? | Yes — honeypot | **Never** |
| Compromise of one grant | All vaults readable | **One user's vault, revocable** |
| Revocation | Requires password change | **One click, instant** |
| Broker autonomy | Full | **Full (after one-time grant)** |
| User consent | None needed | **Explicit, per-user, visible** |

- Master password **never stored**; user key **wrapped** at rest; broker
  **never touches the master password**.
- Compromise of the grant service (and its wrapping keys) yields a user's
  vault — strictly better than master passwords (one vault, revocable, no
  password-reuse blast radius), but not zero-trust. True zero-trust would
  require a per-session user unlock — explicitly not desired.

## 6. Open questions (before implementation)

1. ~~**Key-wrap custody**~~ — **RESOLVED 2026-08-21 (Tigo):** everything for
   a user lives in the **per-user folder** (wrapped key, wrapping key
   `K_user`, broker isolated state) — no central key store.
2. ~~**Revocation UI**~~ — **RESOLVED 2026-08-21 (Tigo):** user revoke via
   the GrantHub page **and** an **admin kill switch** (revoke all grants —
   safety/emergency control).
3. **Step-4 spike** (JS read of the user key on deployed Vaultwarden) —
   **RESOLVED 2026-08-21** (live spike, bot account `webmaster@pmo.city`):
   **the user key IS readable from the authenticated page via injected JS.**

   **Proven — JS reads the full functional user key after user login:**
   - `window.bitwardenContainerService.keyService.getUserKey(userId)`
     resolves to the **SDK SymmetricKey** wrapper; `toBase64()` yields the
     full 64-byte key (32B encryption + 32B auth halves) — exactly what
     the broker needs to wrap and re-mint sessions from.
   - The JS-read key **decrypts real vault data** through the app's own
     `encryptService.decryptString(encString, userKey)`: decrypted the
     test item's name (`cloudbrowser-w1-test` found among 4 ciphers) and
     its password — **byte-for-byte identical to the `bw` CLI reference**
     (`match: true`). No master password touched by the reader.
   - Works right after login, even while the app sits on the
     `#/setup-extension` interstitial — the key is in memory post-unlock,
     so GrantHub's read does **not** depend on the vault UI route.

   **GrantHub implication:** the capture flow is — user logs into
   Vaultwarden in their own browser (plain path or SSO), the GrantHub
   page (same page / frame via the D15 Secrets-button flow) calls
   `keyService.getUserKey(userId)`, takes `toBase64()`, wraps with
   `K_user`, stores in the per-user folder. No master password, no
   headless vault UI, no extension.

   **Operational notes (for D3 broker port / automated tests):**
   - The login page's *visible* email field is the **SSO-path** field
     (`vw-email-sso`): submitting it redirects to Authentik
     (`auth.aikumi.app`) for any email. The **plain path** is the hidden
     `#email` (`vw-email-continue`) + hidden `vw-continue-login` button →
     master-password step → authenticated (active userId in state).
   - Server-to-server reads (FR-9) use the **bw CLI**:
     `bw unlock --passwordenv BW_MASTER_PASSWORD --raw` → session →
     `bw get item`; plaintext stays in the broker process.
   - `/identity/connect/token` with the raw password → 400; the 2026.6.4
     protocol sends `masterPasswordAuthenticationHash` (KDF runs in the
     Bitwarden SDK/WASM) — API-only auth would need the SDK KDF, not
     needed since CLI + JS-read paths both work.

## 7. Links

- FR-9 (deterministic credential broker), FR-10 (IdP token flow) —
  `02-functional-requirements.md`
- D15 broker-driven SSO (Secrets button, parent-browser human door) —
  `23-d15-sso.md`
- Verified session-reuse proof (separate state folder) — 2026-08-21 spike
