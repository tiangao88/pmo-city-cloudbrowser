# Spec 52 — Slot Identity Leak: Previous User's Session Survived the Swap

> **Severity: HIGH — cross-user identity leak (the class Tigo flagged: "one
> profile per user").**
> **Status: INVESTIGATED → FIXED & DEPLOYED → VERIFIED (2026-08-24).**
> Discovered by: Tigo (montigaud's slot showed GrantHub for spike-user).

## 1. Summary

montigaud took slot-1, but the embedded Chrome (kiosk) was still
authenticated as **spike-user**: the `/connect` (GrantHub) page rendered
`spike-user@aikumi.pro`, and the top-bar (router-provided Remote-Email)
showed `montigaud@aikumi.pro` — two identity sources disagreeing because
**tinyauth keys off the browser's session cookie, not the router's state**.

Clicking **Open Secrets** flashed and did nothing: by that moment
montigaud's **15-minute session had expired** (reaper: `EXPIRING montigaud →
released reason=expired`), so `POST /kiosk/open` returned `409 no active
slot` and the button reset.

## 2. Root cause (verified with live evidence)

- **Live Chrome cookie store held spike-user's tinyauth session**:
  `Network.getAllCookies` on the kiosk showed `tinyauth-session-39fcd0f6`
  (36 chars) and a **hard reload** of `/connect` re-rendered as spike-user
  — tinyauth resolved that cookie to spike-user. Disk cookie DBs were empty
  (session cookies are memory-only), so the archive holds the *row* but not
  the live token.
- **The disk profile was empty while Chrome ran**: `/home/neko/.config/
  google-chrome` had **no `Default/` dir** — Chrome kept its in-memory
  (previous-user) session while the profile beneath it was wiped/restored.
- **Mechanism: an interleaved `/wake` + `/suspend`** during the offer/re-offer
  churn. `restart-api` serves `/wake`, `/suspend`, `/release` from threaded
  HTTP handlers with **no lifecycle lock**. A wake (restore→start) racing a
  suspend (stop→archive→wipe) leaves a half-restored profile; the running
  Chrome keeps the old user's in-memory session; and `archive_user` can then
  overwrite the user's real archive with an empty shell.

## 3. Fixes (deployed, spec 52)

`restart-api.py`:
1. **`_lifecycle_lock`** — serialises `do_wake` / `do_suspend` (and the
   release path which calls do_suspend). No more interleaved swap/teardown.
2. **`archive_user` guard** — refuses to archive a profile lacking
   `Default/` + `Preferences` (empty/half-restored), keeping the existing
   archive. Prevents the empty-archive overwrite.
3. **`restore_user` guard** — treats an archive whose profile lacks
   `Default/` + `Preferences` as a fresh wake instead of restoring an empty
   shell.

`router.py` (`_connect_page` text, in-kiosk UX):
- Button relabelled **🔒 Open the PMO City vault**; step text now says it
  opens **Vaultwarden in a new tab** inside the CloudBrowser window; error
  message explains the session-ended case instead of "could not reach kiosk".

## 4. Verification

- Harness: **103/103 PASS**.
- Deployed to scripts volume + restarted restart-api (both slots) + router.
- **Live (slot-1, montigaud wake):** clean wake → kiosk `/connect` redirects
  to **Authentik SSO login** (not "GrantHub: spike-user") — the previous
  user's session is gone; montigaud SSOs as himself.

## 5. Notes

- Session cookies are memory-only: after any clean slot handover the new
  owner **must SSO again inside the kiosk** (FR-10 boundary) — the login
  page is correct, not a bug.
- `CB_HUMAN_MAX_SESSION_MIN=15` is short for a live demo; the 409 "no
  active slot" on Open Secrets is a direct consequence. Raise per-pilot
  need (config only, no code change).
