# 60 — PowerMail fill end-to-end from the grant alone (2026-08-25)

Status: **DONE — LIVE-VERIFIED** (commit `f96c721` + `…`)

## What was proven

The D3 final row: **"Broker fills a declared site's login end-to-end on a
pilot site"** — with ZERO user unlock. The broker:

1. Unwrapped the stored grant (key + session legs, AES-GCM under K_user)
   — inline, slot-side, Python 3.9-safe (granthub.py's `X | None`
   annotations prevent direct import on the slot's 3.9; the unwrap
   logic is inlined via `gcm.py`).
2. Minted a fresh vault access token (`grant_type=refresh_token`).
3. `/api/sync` → located the Powermail item (id
   `1d1dcee2-f6bc-4cdd-98a0-e911e2dd9a72`).
4. Decrypted username + password (AesCbc256_HmacSha256_B64, MAC
   validated).
5. Opened `https://go.powermail.fr/` in the kiosk (PUT /json/new).
6. Filled the Roundcube form (`_user` / `_pass`) via CDP + native
   setter, clicked Connexion.

Result:

```
creds OK: username=pmoc-spike-user password_len=14
tab open OK: https://go.powermail.fr/
form fill OK, submitted=True
final url: https://go.powermail.fr/?_task=mail&_mbox=INBOX
final title: PowerMail :: Boîte de réception
RESULT: OK — PowerMail session started
```

FR-9: plaintext (key, refresh token, password) stayed inside the slot
process; the script prints status/lengths only.

## Notes / learnings

- The slot's scripts volume is mounted **read-only** inside the
  container — new tooling must be written to the volume from the host
  side (`tar | ssh 'tar xzf - -C $VOL'`), not `cat >` via docker exec.
- `python3 -m py_compile` inside the slot fails on the read-only
  `__pycache__` — use `python3 -B` (bytecode cache off) or compile
  locally first.
- `wrapped_key` in the grant store holds the RAW 64-byte user key
  (granthub.wrap base64-decodes before wrapping) — inline unwraps must
  NOT `.decode()` it as UTF-8 (first run hit
  `UnicodeDecodeError: 0xdf`).
- Idle-suspend (20 min) can fire mid-run; a keepalive touching
  `/tmp/cdp-activity` every 15 s was re-armed during the run (matches
  the established probe-window pattern).
- Vault UI state is irrelevant to the broker path: the fill worked with
  the vault tab at `#/lock` in the background — the grant store is the
  only dependency.

## Files

- `scripts/pm-fill.py` — slot-side, self-contained (gcm.py + vendored
  pyaes; reuses sso-broker's CDP client via importlib, never runs its
  main()).
- `specs/60-powermail-fill-e2e.md` — this doc.
- DoD: `20-w2-dod.md` D3 first row → `[x]`; `27-w2-deltas.md` D3 row
  updated.

## Next

- D2 (TOTP seed via the same grant) — **IMPLEMENTED 2026-08-26 (spec 73)**:
  `totp.py` + `vault_client.py` + broker Authentik code-stage fill +
  router `/otp/*` code-exchange; live verification pending Tigo (chat-ask
  + autonomous runs).
- D15B session health + TOTP leg; D1 retire static NEKO_PASSWORD (now
  safe — broker is the per-user credential mechanism).

## Re-validation (2026-08-25, second live run — spike-user session)

Re-run on the live fleet (slot-1, spike-user active, `/connect/status`
= `{shared:true, session:true, usable:true}`): identical pass, zero
user unlock —

```
step1: unwrap + mint + sync + decrypt ...
creds OK: username=pmoc-spike-user password_len=14
tab OK (reused): https://go.powermail.fr/
form fill OK, submitted=True
final url: https://go.powermail.fr/?_task=mail&_mbox=INBOX
final title: PowerMail :: Boîte de réception
RESULT: OK — PowerMail session started
```

Screenshot-verified in the kiosk: logged-in PowerMail inbox
(`pmoc-spike-user@powermail.fr`, Boîte de réception, Déconnexion
visible). Grant store = the only dependency (vault UI state
irrelevant). Invocation: `docker exec slot-1-… python3 -B
/etc/neko/supervisord/pm-fill.py`.
