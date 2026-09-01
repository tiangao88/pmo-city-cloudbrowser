# 68 — Per-user Downloads storage + broker per-owner identity (2026-08-25)

Status: **DEPLOYED + LIVE-VERIFIED** (commit TBD)

## Directive (Tigo, 2026-08-25)

> "Definitely the download should be per user, not per slot, because
> slots are shared. Again, users don't share anything. You don't have
> to wait for my authorization for that. Now, in the Montigo session, I
> have an issue because the broker logged with Spike user identity. We
> need to fill that Montigo has his own Vaultwarden identity."

## Part 1 — Per-user Downloads storage

### Before
The slot's physical Downloads volume (`/home/neko/Downloads`, per-slot)
was only **profile-wiped** on suspend (`wipe_profile()`): `archive_user`
copied the files into the user's archive, but the slot's Downloads dir
**kept them** and `.slot-user.json` kept the old owner. Result: the slot
volume accumulated user files across owners (observed: slot-1 + slot-2
both held montigaud's and spike-user's PDFs) — exactly the "shared
asset" Tigo flagged.

### Change (`restart-api.py`)
- New `clear_slot_user()`: resets `_slot_user`/`_slot_index` and removes
  the on-disk `.slot-user.json` marker.
- `_do_suspend_impl()`: after `archive_user(user)`, now calls
  `wipe_slot_dirs()` (profile **and** Downloads volume) + `clear_slot_user()`
  instead of the profile-only `wipe_profile()`.
- Net effect: **a suspended/released slot physically holds nothing of
  any user** — no Downloads files, no owner marker. The durable per-user
  store is the archive (`/data/sessions/<user>/Downloads`), which is
  restored onto the slot on the user's next wake (`restore_user`).

### Live verification (slot-2)
- Wake montigaud → `WAKE 200 {user: montigaud}`, marker
  `{user: montigaud@aikumi.pro}`, Downloads = montigaud's 2 PDFs
  (restored from archive).
- Suspend → `SUSPEND 200`, `NO-MARKER`, Downloads dir empty.
- Archive intact after wipe: montigaud's 2 PDFs still present
  (`/data/sessions/montigaud@aikumi.pro/Downloads/`).
- Pre-fix residue on slot-2 (stale spike-user marker + files from
  08-24) cleaned manually during the audit.

## Part 2 — Broker per-owner identity (never spike-user)

### Root cause (Tigo: "broker logged with Spike user identity")
The broker's `username/password` were module globals loaded **once**
(`load_creds()` only ran when `username is None`), so a broker process
that had loaded spike-user's creds (or the pre-66 shared file) **kept
them in memory across owner changes** — montigaud's kiosk auto-logged
into the vault as spike-user. The legacy shared-file fallback was also
still present in code.

### Change (`sso-broker.py`)
1. **Stale-identity guard in `main()`**: on every owner change
   (`owner != last_owner`), in-memory `username`/`password` are reset
   to None and `_owner_cache` cleared — the next login is re-resolved
   against the NEW owner's per-user file only.
2. **Legacy shared fallback REMOVED** from `load_creds()`: a broker
   login is now per-owner only; if the owner has no per-user creds
   file, it logs "no per-user creds for owner X — waiting for the
   owner's own Vaultwarden login" and waits (fail-closed, never a
   shared identity).

### How montigaud gets his OWN identity
The broker's per-user identity does **not** require the
`sso-creds.json` username/password file. The capture path works from
the owner's own login: montigaud opens the vault in the kiosk and logs
in with his own Vaultwarden account → the broker captures HIS key +
refresh token under owner=montigaud (`post_grant`) → the grant becomes
usable with montigaud's identity. With the stale-identity guard, the
broker never substitutes spike-user's session. (The
`sso-creds.json` username/password auto-fill remains an optional
convenience that can be provisioned later — e.g. Tigo placing a
per-user b64 file — but is NOT required for per-owner identity.)

## Files / deploy
- `restart-api.py`, `sso-broker.py` → scripts volume (both slots),
  md5-verified, supervisord restarted (restart-api + sso-broker).
- Harness: 114/114 PASS.
- Broker after restart: `slot owner: None — GrantHub capture disabled`
  (slot released); owner change clears creds.

## Follow-ups
- Provision montigaud's `sso-creds.json` (optional auto-fill
  convenience) OR rely on the capture path (montigaud logs in once in
  the kiosk) — the latter is sufficient and needs no credential
  handling by the agent.
- Test the D7 footer with montigaud's own grant once he captures.
