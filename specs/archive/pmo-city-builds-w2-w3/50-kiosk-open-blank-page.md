# Spec 50 — GrantHub "Not Shared" Opened a Blank Page in the Kiosk

> **Severity: MEDIUM — UX broken (GrantHub capture unreachable from kiosk).**
> **Status: INVESTIGATED → FIXED & DEPLOYED → LIVE-VERIFIED (2026-08-23).**
> Discovered by: Tigo (real session: click Not Shared → blank page, stuck).

## 1. Summary

Inside the embedded Chrome (kiosk), clicking the **🔗 Not Shared** (GrantHub)
pill opened a **blank page** and the user was stuck. Expected: the `/connect`
capture flow (SSO → Vaultwarden login → grant page).

**Root cause: GH.8's relative-URL migration broke the kiosk-open path.**
`GRANTHUB_URL` changed from absolute
(`https://cloudbrowser.dev01.pmo.city/connect`) to relative (`/connect`).
The router's `_whitelisted_surface` accepts same-origin paths as-is, and the
slot's restart-api opens the URL via Chrome's `/json/new?<url>` — which
**cannot resolve a relative path** (no base origin) → Chrome opens an empty
`about:blank` tab and never navigates.

## 2. Evidence

- Router log (2026-08-23, Tigo session): `POST /kiosk/open?url=%2Fconnect
  user=spike-user@aikumi.pro kiosk-open slot-1: /connect` — relative path
  forwarded verbatim to the slot.
- Live repro: `open_url("/connect")` → `chrome /json/new?%2Fconnect` →
  tab created, URL never resolves → blank.
- Secondary finding (same window): slot-1 `title-proxy` had just restarted
  (`uptime 0:02:47` vs neko `2:54:24`); the router's entry fetch
  (`GET /?pwd=…`) hit `Connection refused` once and raw-fallbacked — this
  is why the first "Open Browser" click bounced back to the countdown page
  (the page itself is by-design two-step: offer → session page with
  countdown + button; auto-load fires when the slot is ready).

## 3. Fix (deployed, md5 `8c909820`)

`router.py _kiosk_open`: same-origin whitelisted surfaces are now resolved
to an **absolute public URL** against the request's `Host` +
`X-Forwarded-Proto` before POSTing to the slot's `/open-url`:

```
/connect  →  https://cloudbrowser.dev01.pmo.city/connect
```

The kiosk then reaches `/connect` through Caddy/tinyauth exactly like the
user's main browser (Remote-Email is set by tinyauth from the kiosk's SSO
session cookie). Other kiosk-open sources (landing `?goto=`, connect-page
pills, session-bar pill) all share the same router path → all fixed.

## 4. Verification

- **Harness:** 102/102 PASS — new assertion: `POST /kiosk/open?url=/connect`
  must deliver `https://cloudbrowser.dev01.pmo.city/connect` to the slot
  (not `/connect`).
- **Live (slot-1, spike-user):** kiosk-open `/connect` with public Host →
  kiosk tab navigates to `https://auth.aikumi.app/if/flow/…` (Authentik SSO
  login) — the designed capture chain, no more blank tab. Bad-Host test
  (Host `127.0.0.1`) → `https://127.0.0.1/connect` → `ERR_CONNECTION_REFUSED`
  → O6 error tab (proves the absolutization uses the request Host).
- Deployed to scripts volume + router container (`docker restart
  router-okixw2fxnwn1lakxvxajodww`); volume/container md5 `8c909820`.

## 5. Notes

- The user must complete SSO **inside the kiosk** once per fresh profile
  (tinyauth cookie lives in the kiosk profile archive) — this is the
  designed FR-10 boundary (SSO token never leaves the user's browser
  session; the broker authenticates independently).
- Follow-up (not blocking): the entry-fetch `Connection refused` race when
  title-proxy respawns — the router could retry the slot fetch once before
  raw-fallback.
