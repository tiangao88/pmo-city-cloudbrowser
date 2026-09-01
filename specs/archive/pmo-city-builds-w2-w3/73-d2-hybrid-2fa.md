# 73 — D2: Hybrid 2FA for autonomous logins (TOTP / chat-ask)

> **Refactor classification — 2026-09-01:** The implementation and evidence in
> this document are Authentik-specific. The generic MFA policy is now defined
> in `85-credential-broker-prd.md` and `87-broker-security-model.md`; this
> document remains the adapter-specific D2 record.

Date: 2026-08-26 · Status: **IMPLEMENTED AND LIVE QUALIFIED** · DoD D2 (20-w2-dod.md) · FR-5 gate Q3
(decided 2026-08-16) · execution checklist: 47-w2-items-2-4-execution.md row 5
(spec 47.md) · Phase-B hook: 23-d15-sso.md step 4.

## Security directive (FR-5/FR-6, locked)

For **autonomous logins** (broker-driven), 2FA is hybrid:

- **TOTP seed present** in the user's share-vault login item → the broker
  computes the current code (RFC 6238) and fills it — fully autonomous.
- **No seed** → the broker NEVER invents a code. It raises a *code-request*
  visible to the agent; the agent asks the employee in chat; the employee's
  one-time code is POSTed to the router and the broker fills it.
- **Never autonomous 2FA without a stored secret.** No path where a missing
  seed is skipped, guessed, or brute-forced.
- Plaintext (seed, computed code, user-supplied code) **never** appears in
  logs, chat, LLM context, or on disk. Status/booleans only (FR-9).
- The fill happens ONLY on the two whitelisted SSO origins
  (auth.pmo.city / auth.aikumi.app), in the Authentik TOTP stage
  (ak-stage-authenticator-validate-code), same shadow-DOM discipline as the
  identification stage (spec 23). Verified against the LIVE Authentik
  2025.8.1 bundle AND goauthentik/authentik main (2026-08-26): the code
  input is `input[name=code]` (autocomplete=one-time-code) in both; submit
  is `button[name=continue]` on main / plain `button[type=submit]` on
  2025.8.1 — the fill script accepts both; device picker buttons are
  `button.authenticator-button` in both.

## Current gap (root cause)

`sso-broker.py` fills only the Authentik **identification** stage. When the
user has TOTP enrolled, Authentik presents the code stage after submit; the
broker's `fill_and_submit` sees the tab still on auth origins, retries once,
logs FAILED and gives up → the human must finish login manually (the exact
manual 24 h re-login D15 was meant to remove).

Broker credentials also still come from the per-owner `sso-creds.json`
convenience file (spec 66/68); the natural per-user source — the user's own
GrantHub grant (key + session legs) — was never wired in. D2 wires it: the
broker reads the owner's SSO login item **from the owner's own grant** at
login time (spec 68 follow-up "per-user creds via grant path (D3.4/D2)").
The `sso-creds.json` file becomes unnecessary (kept working if present).

## Probe evidence (2026-08-26, spike-user vault, status-only)

- 5 login ciphers; org `55199747-…-c03c` owns 3 (shared collection).
- `Aikumi Connect` (personal, id 3569e663-…): URI `https://auth.aikumi.app`,
  username+password, NO TOTP — the SSO identification item.
- `dcac52f7-…` (org item): **has native `login.totp`** — the D2 TOTP item
  ("Authentik Spike User"). Org items are encrypted with the ORG key; the
  org key must be resolved from `keys.organizationKeys` (encrypted with the
  user key) — **sync currently returns `organizationKeys: []`** for
  spike-user, so org items are NOT decryptable by the broker yet.
  → **Open point A**: grant spike-user org-key access (add as org member or
  move the TOTP item to a personal/decryptable scope). Without it, the
  autonomous leg cannot read the seed.
- ⚠️ Incident note: the 2026-08-26 probe rotated the stored refresh token
  without persisting → grant session leg revoked (`invalid_grant`). The
  production paths (grant-sync, pm-fill, vault-client) persist rotation;
  the probe was ad-hoc. Recovery = one fresh SSO round-trip in the kiosk
  (session-leg re-capture, spec 59). Folded into the live-test plan.

## Design (locked)

### New: `scripts/totp.py` (slot-side, pure stdlib, 3.9-safe)

- `normalize_secret(raw)` — strips whitespace, uppercases, accepts
  `otpauth://totp/…?secret=…` (and `&issuer=` etc.), validates base32
  (with `=` padding tolerance), falls back to raw string on non-base32.
- `totp(secret, at=None, step=30, digits=6, algo="sha1")` — RFC 6238:
  HMAC-SHA1(secret_b32, counter=floor(at/step)); dynamic truncation; zero
  padding. `at` injectable for tests (RFC vectors).
- Deterministic, no deps, no I/O, no logging.

### New: `scripts/vault-client.py` (slot-side, 3.9-safe, pure stdlib)

Reads the owner's login material from the owner's OWN grant (D3.4/D2):

- `unwrap_grant(root, user)` → (key64 bytes, refresh_token) — ported from
  pm-fill (gcm.py + pyaes), refuses revoked/missing.
- `mint(root, user)` → access token; **persists the rotated refresh token
  back into the grant store** (rotation discipline, spec 59).
- `sync_items(root, user)` → decrypted-name view of login ciphers:
  `[{id, name, uris, username, password, totp_secret, org}]`.
  - org items: resolve `keys.organizationKeys[]` → org key (decrypt with
    user key) → decrypt item fields with the org key; missing org key →
    item marked `org_key_missing: True` (never a silent wrong decrypt).
- `find_ssologin(items, item_id=None, exact_name="Authentik Spike User")` —
  fail-closed selection: use the immutable cipher ID when configured,
  otherwise require one exact decrypted item name. The selected item must
  carry an exact HTTPS URI on `auth.aikumi.app` or `auth.pmo.city`; URL
  userinfo/non-443 ports, zero matches and duplicate matches are rejected.
- `totp_secret(item)` — native `login.totp` first; else custom field named
  `TOTP`/`totp` (decrypted name, any type); else None.
- FR-9: values stay in-process; callers log status only.

### Modified: `scripts/sso-broker.py` — login flow v2

- Identification: replace `load_creds()` (sso-creds.json) with
  `vault_login(owner)`: unwrap grant → mint → sync → find SSO item →
  (username, password, totp_seed). If grant unusable / item missing →
  log status + WAIT (never another user's creds, spec 66 stays).
  The legacy `sso-creds.json` file, when present for the owner, remains a
  fallback (documented; not provisioned anymore).
- **NEW `handle_mfa(cdp, target, owner, seed)`** after identification
  submit, while the tab is still on auth origins:
  1. Poll for `ak-stage-authenticator-validate-code` (shadow DOM).
  2. **Autonomous leg**: seed present → compute code → fill `input[name=code]`
     → click `button[name=continue]` → poll until tab leaves auth origins;
     on stage re-render (rejected code) retry ONCE with a fresh code
     (30 s window); second failure → log + fall through to chat-ask.
  3. **Chat-ask leg**: no seed (or autonomous failed) →
     `POST /otp/request` (broker Bearer + Remote-Email) → poll
     `GET /otp/pending` every 2 s up to `SSO_MFA_TIMEOUT_S` (default 180) →
     when a code is delivered → fill + submit → poll for exit; wrong code →
     single retry via a NEW request (agent asks again); timeout → log
     `mfa: waiting for human` and stop touching the page (never a hard
     block — the employee can type the code in the kiosk).
- Codes and seeds are function-local; log lines are status-only
  (`mfa: autonomous ok`, `mfa: code requested (no seed)`, `mfa: user code
  submitted ok`, `mfa: code rejected`).
- Kill-switch unchanged (`SSO_BROKER_ENABLED=false`); heartbeat watchdog
  unchanged (MFA waits are bounded by timeouts).

### Modified: `scripts/router.py` — OTP code-exchange endpoints

In-memory (never persisted, never logged), keyed by Remote-Email:

- `POST /otp/request` — broker Bearer (`CB_GRANTHUB_BROKER_TOKEN`) +
  Remote-Email → (re)arms a pending entry, TTL `CB_OTP_TTL_S` (default 180).
- `GET /otp/pending` — broker Bearer + Remote-Email → `{code|null, ttl_s}`;
  the code is returned at most ONCE (cleared on read).
- `POST /otp/submit` — agent Bearer (`CB_OTP_AGENT_TOKEN`, NEW env) +
  Remote-Email → stores the code (single-use, TTL-bounded). 401 without
  email, 403 wrong/missing bearer, 501 when `CB_OTP_AGENT_TOKEN` unset
  (fail closed).
- Code never written to logs or state file; router restart drops pendings
  (broker falls back to waiting/timeout — acceptable, codes live 30 s).

### Compose / env (fleet)

- Router: `CB_SLOT_1_TOKEN` / `CB_SLOT_2_TOKEN` use distinct Coolify magic
  variables; router maps bearer → slot → current owner. The legacy shared
  broker token is disabled in the qualified architecture. Router alone mounts
  `/data/sessions`.
- Slots: each receives only its own `CB_SLOT_N` + `CB_SLOT_<n>_TOKEN` and
  fetches grant material through `/connect/grant/material`; slots do NOT mount
  the shared sessions store. Refresh-token rotation persists through the same
  slot-authenticated router boundary (`GRANT_POST_URL`).
- Router retains `CB_OTP_AGENT_TOKEN=${SERVICE_PASSWORD_64_OTPAGENT}` and
  `CB_OTP_TTL_S=${CB_OTP_TTL_S:-180}`. OTP requests are opaque challenge IDs
  bound to slot, owner and target; submit and fetch are one-shot.

## Test plan (TDD)

`scripts/test-d2.py` (local, no live vault):

1. **totp**: RFC 6238 vectors (secret 12345678901234567890 →
   GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ) at T=59 → 287082, T=1111111109 →
   07081804, T=1111111111 → 14050471, T=1234567890 → 89005924,
   T=2000000000 → 69279037, T=20000000000 → 65353130; otpauth:// URL
   parsing; base32-with-spaces; non-base32 fallback; zero padding.
2. **vault-client**: encstring roundtrip (encrypt→decrypt with the same
   primitives), plaintext passthrough, MAC failure raises, org-key path
   (fake sync with organizationKeys), `find_ssologin` by URI and by name
   hint, `totp_secret` native > custom field > None.
3. **sso-broker MFA decision**: no seed → `POST /otp/request` issued;
   seed → autonomous fill chosen; code never in returned strings of log().
4. **router OTP endpoints**: request → pending armed; submit → pending
   returns code once then clears; TTL expiry; 401/403/501 fail-closed;
   code absent from router state file + log output.

## Live verification plan (needs Tigo, staged)

**Stage 0 — repair (Tigo, ~2 min):** open the kiosk, log in as spike-user
(manual identification, phone TOTP), open Secrets → SSO round-trip re-captures
the session leg → `usable:true` again. (Repairs the probe incident.)

**Stage 1 — chat-ask leg (Tigo, ~5 min):** grant usable again; with the TOTP
item temporarily WITHOUT a readable seed (see Open point A) — or the item
temporarily unshared — the broker hits the code stage → requests code →
agent asks Tigo in chat → Tigo sends a fresh code (private 1:1 Home chat,
or this group while alone) → broker completes login → SSO session cookie
present, app tab loads. Log evidence status-only.

**Stage 2 — autonomous leg (Tigo, ~3 min):** Tigo (or admin) resolves
Open point A so the broker can decrypt the TOTP item. Clear kiosk cookies →
open cloudfiles → broker fills identification + computes TOTP → login
completes with ZERO user action. Evidence: broker log
`mfa: autonomous ok` + cookie + app tab.

**Stage 3 — negative:** with the seed unreadable again, verify the broker
NEVER bypasses: code-stage present + no seed → request issued (never a
guessed code); a wrong submitted code is rejected and retried once.

## Open points

- **A (blocks autonomous leg):** org-key access for the TOTP item. Options:
  (1) Tigo moves "Authentik Spike User" to a personal (non-org) login item in
  spike-user's vault (fastest, matches FR-6 per-employee collection), or
  (2) grant spike-user org membership with the org key (admin-side). Tigo
  decides; the broker supports both (org-key resolution implemented).

## Files

- new: `scripts/totp.py`, `scripts/vault-client.py`, `scripts/test-d2.py`,
  `specs/73-d2-hybrid-2fa.md`
- modified: `scripts/sso-broker.py`, `scripts/router.py`,
  `specs/26-s7-fleet-compose-v2.yaml`, `specs/20-w2-dod.md` (D2 boxes),
  `specs/27-w2-deltas.md` (D2 row), `specs/22-w2-progress.md`,
  `specs/23-d15-sso.md` (Phase B step 4 note), `specs/60-powermail-fill-e2e.md`
  (Next note)
