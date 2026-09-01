# Spec 55 — Grant persistence + broker watchdog + reload-hang hardening

> **Status: DONE (2026-08-24).** Tigo reported two problems after taking
> slot-1 as spike-user:
> 1. "Not Shared" stayed **red** even after granting in Vaultwarden.
> 2. Ctrl+Shift+R **hung forever** ("connecting, connecting, connecting").

## 1. Diagnosis (all verified live)

**1a. The grant was gone — archive wiped it.**
`/connect/status` returned `shared:false`; spike-user's
`/data/sessions/<user>/` had **no `grant/` dir**. The 07:53 grant (verified
`shared:true` earlier) was destroyed when the session expired and
`archive_user` did `shutil.rmtree(<user>/)` — which deletes the router's
grant store (`GRANT_ROOT=/data/sessions`) along with the profile.

**1b. The broker was FROZEN — no capture happened.**
`sso-broker` (slot-1) logged its last line at 09:47:26; at 09:57 it was
still "RUNNING" but silent — a single CDP pass had blocked forever while
Chrome was coming up. Even though Tigo opened/unlocked Vaultwarden, the
broker could never read the key → no `POST /connect/grant` (zero such
requests in the logs).

**1c. The reload hang — title-proxy restart gap.**
On wake, restart-api stops title-proxy (idle) and starts it (wake). The
router's spec-51 single 0.8s retry was too weak: the client got a
Connection-refused page during the startup window and neko's WS retry is
weak → "connecting" forever.

**1d. (same class) empty-archive overwrite.**
After the wipe, `archived spike-user@aikumi.pro (4 KiB)` — the spec-52
guard (Default/Preferences exist) passed on an empty shell, so a 4 KiB
archive replaced real data.

## 2. Fixes (deployed)

- **restart-api.py `archive_user`:** copies the existing `grant/` dir into
  the new archive before the swap — grants survive session end.
- **sso-broker.py:** heartbeat watchdog thread — main loop refreshes a
  timestamp each pass; if stale > 90 s, `os._exit(1)` so supervisord
  autorestart recovers the daemon (a stalled CDP op can no longer freeze
  capture forever). Also `sock.settimeout(10)` belt-and-braces in the WS
  handshake.
- **router.py index fetch:** spec-51's single 0.8s retry → bounded 8×
  0.5s retry loop, so the viewer is only served once the slot's
  title-proxy answers (fallback still raw-proxy + watchdog injection).
- **restart-api.py `archive_user` (hardening):** if an existing archive is
  present and the on-disk profile is < `MIN_PROFILE_ARCHIVE_B` (default
  5 MiB), skip archiving — an empty shell never replaces a real archive.
  Env: `MIN_PROFILE_ARCHIVE_B`.

## 3. Verification

- Harness **109/109 PASS** (spec-51/40 raw-fallback paths covered by the
  new loop).
- Deployed: scripts volume md5-verified (router.py `1369c5b9…`,
  restart-api.py `b14b6457…`, sso-broker.py `c567d3ba…`), router restarted,
  restart-api + sso-broker restarted on both slots; broker re-armed with
  capture ("slot owner: spike-user — GrantHub capture armed").
- Broker freeze: after the fix, a stalled pass force-exits within 90 s and
  supervisord restarts it (no permanent dead capture).

## 4. User-visible behaviour after this fix

- Grant once → it persists across session ends (no re-grant per slot).
- Taking a slot + Ctrl+Shift+R no longer hangs (page served only when the
  slot is ready).
- The top-bar pill flips to 🔗 Shared (green) once the grant exists and the
  page (with the spec-53 poller) is loaded.
