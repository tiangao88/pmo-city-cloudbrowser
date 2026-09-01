# 66 — SECURITY INCIDENT: broker auto-logged the kiosk as the WRONG user (shared static SSO creds) (2026-08-25)

Status: **ROOT-CAUSED → FIXED → DEPLOYED → LIVE-VERIFIED** (commit TBD)

## Report (Tigo, 2026-08-25)

> "Now the session is with user montigaud, and I have an issue. When I
> click Not shared, it opens the GrantHub page, sent me to SSO, but
> then automatically logged me with the spike-user password, which I
> did not even have to type. This is a security breach. How come Chrome
> auto logs a different user?"

## Root cause (live evidence)

The slot **sso-broker** carries a **shared static credential file**
`/etc/neko/supervisord/sso-creds.b64` = `{"username":"spike-user",
"password":"p41GmWMllq8YMx8W"}` — the legacy W1 bot account, deployed
on the shared scripts volume (every slot, every user). On ANY detected
login tab (`auth.pmo.city`/`auth.aikumi.app`), `load_creds()` read that
file and auto-filled **spike-user's password** into Authentik. Because
the slot owner's identity (montigaud) is NOT tied to the broker login,
montigaud's kiosk SSO silently authenticated as **spike-user** —
exactly Tigo's report. The broker's log confirms the auto-fill:
`login tab detected → filled + submitted → login ok` + "session cookie
check: 0 .pmo.city cookie(s)" (tinyauth cookie absent → the SSO session
it established was the vault identity, not the tinyauth user).

Contributing facts:
- The file was **shared** (one copy for all users) and **static**
  (W1-era bot creds); the broker never consulted the slot owner.
- `load_creds()` shredded the file after load — but the volume copy
  persisted (read-only mount), so every broker restart re-armed it.
- The GrantHub page + vault SSO are **identity-bound to whoever
  Authentik authenticates**, so the wrong identity propagated into the
  vault session.

## Fix (deployed)

**sso-broker.py — per-slot-owner creds:**
1. New `_owner()` + `_owner_creds_file()`: the broker now resolves the
   **current slot owner** (`.slot-user.json`) and reads
   `/data/sessions/<owner>/grant/sso-creds.json` (per-user, b64 JSON
   username/password) — a broker login always logs in as the slot
   owner.
2. Legacy shared file path retained ONLY as a loudly-logged fallback
   when the owner has no per-user creds, with a stale-identity guard
   (never re-arms for a different owner once any per-user identity was
   used).
3. **Shared `sso-creds.b64` removed from the scripts volume** (both
   slots; `rm` via alpine volume container). It can no longer re-arm.
4. Both slots' sso-broker restarted; md5-verified.

## Verification

- Broker restart log: `slot owner: montigaud@aikumi.pro — GrantHub
  capture armed` (per-owner resolution active).
- Kiosk Authentik session + tinyauth cookies **cleared** → reload of
  `/connect` now lands on the **Authentik identification screen**
  (username input present, NO auto-login, no password fill). The
  auto-login-as-spike-user vector is dead.
- Harness 114/114; broker py_compile clean.

## Required follow-ups (Tigo)

1. **Per-user creds for real users:** the broker can only auto-login as
   the owner once `/data/sessions/<owner>/grant/sso-creds.json`
   exists. For montigaud (and each real user), we need that file —
   either by (a) the user granting through the kiosk `/connect`
   (capture path) — **D3.4/D2 chain**, or (b) Tigo placing the b64
   creds file explicitly (same trust as the old file but per-user).
2. **Decide the bot-account role:** with per-user creds in place, the
   spike-user bot account is no longer a kiosk identity — it remains
   only as the D10 non-member test account.
3. **Log/audit:** broker now logs which owner identity it filled —
   monitor `slot owner` lines per session.

## Follow-up (2026-08-25, Tigo): full per-user shared-asset review

Tigo: "Everything has to be separated per user... anything that is
shared is suspicious — review that in the technical design." The
complete shared-asset audit is **spec 67** (`67-peruser-isolation-review.md`).
Key outcomes:
- **Spec 66 fix stands** as the shared-credential vector closure
  (per-owner broker creds + shared file removed).
- Remaining shared items = infrastructure creds/code, NOT user data:
  `NEKO_PASSWORD` (D1 retirement), Coolify magic-var API tokens (by
  design), shared scripts volume (code only), router (single entry
  point). No cross-user credential leakage found outside the spec-66
  vector.
- Open decisions: per-slot Downloads vs per-user Downloads (O-2),
  remove `.bak-*` files (O-3), provision per-user broker creds for
  montigaud (O-4, grant path).
