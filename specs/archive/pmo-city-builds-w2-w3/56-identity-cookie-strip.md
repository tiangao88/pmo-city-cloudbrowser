# Spec 56 — Identity cookies are never archived or restored

> **Status: DONE (2026-08-24).**
> Tigo: "When I click Not Shared in a session with user montigaud, I'm
> still having the GrantHub connected with the spike-user. We really need
> to flush that out."

## 1. Root cause (verified live)

The GrantHub /connect page identity comes from **whoever's tinyauth
session cookie the kiosk Chrome holds** (tinyauth forwardAuth resolves the
cookie → Remote-Email). montigaud's **archive on disk** held a stale
`tinyauth-session-39fcd0f6` cookie on `.pmo.city` that belonged to
**spike-user** (from the earlier leak era). Every wake restored that
archive → the kiosk always SSO'd as spike-user → GrantHub rendered for
spike-user while montigaud owned the slot, and "Open the PMO City vault"
409'd (spike-user has no active slot) — the button flashed.

Direct read of the archived Cookies DBs confirmed the poison:
`montigaud@aikumi.pro` archive: `('.pmo.city', 'tinyauth-session-39fcd0f6')`
+ 2 Authentik cookies; `spike-user@aikumi.pro` archive: same tinyauth
cookie.

## 2. Fix

**restart-api.py `_strip_identity_cookies(profile_dir)`** — deletes cookies
where `host_key LIKE '%.pmo.city%' OR host_key LIKE '%aikumi%' OR name
LIKE 'tinyauth%'` from a profile's `Default/Cookies`:
- called in `archive_user` (on the staged archive copy) → **archives never
  carry SSO identity**;
- called in `restore_user` (on the restored profile) → belt-and-suspenders
  for archives that predate the strip.

Chrome is stopped in both paths, so the Cookies DB is safe to edit.

**Existing poisoned archives purged in place** (sqlite3 DELETE):
montigaud 4→1 cookies, spike-user 7→6, spike-user2 untouched.

**Live kiosk purged** via CDP `Storage.clearCookies` + navigate → the
kiosk now sits on the Authentik login with zero cookies.

## 3. Effect

Every session now SSOs fresh as the **slot owner** (the FR-10 boundary —
the kiosk is a separate server-side browser). No stale identity can
survive an archive/restore cycle again. GrantHub always shows the current
owner, and the vault-open button works for them.

## 4. Note

Re-login per session is the intended security posture (and the broker's
Authentik auto-fill can make it seamless for provisioned users). If a
persistent SSO across sessions is ever wanted, it must be keyed to the
slot owner's archive deliberately — never by carrying a foreign cookie.
