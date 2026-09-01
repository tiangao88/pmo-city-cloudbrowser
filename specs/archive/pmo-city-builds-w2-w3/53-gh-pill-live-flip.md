# Spec 53 — GrantHub pill live-flip in the top bars

> **Status: DONE (2026-08-24).** Tigo: after granting, the top-bar pill
> still read "🔗 Not Shared" (red) while the /connect card said "Shared"
> (green).

## 1. Root cause

Server state was correct (`/connect/status` → `shared: true`); the
**top-bar pill was static**. Each surface renders the pill once:

- title-proxy (kiosk/neko viewer top bar) — server-side `_shared_state()`
  at page load; injected `<a>` never re-queried.
- router landing page (`_top_bar` variant="landing") — same.
- `/connect` card — **already** polls `/connect/status` every 2 s (green
  card in the screenshot proved the state was fine).

## 2. Fix

- **title-proxy.py**: injected script now starts a 2 s poller
  (`fetch(_ghu)` where `_ghu` = `GRANTHUB_STATUS_URL`, browser-facing
  relative path) that repaints the `.cb-tool-shared a` pill
  (text + color `#22c55e` / `#ef4444`). Guarded: no-op when the env is
  unset.
- **router.py**: landing top-bar pill gets `id="ghPill"`; landing page
  gains the same 2 s poller (flips label + `cb-shared`/`cb-noshared`
  class). Queue page unchanged (pill intentionally hidden there, spec 48).

## 3. Verification

- Harness: 103/103 PASS.
- Deployed: scripts volume (router.py `21dde797…`, title-proxy.py
  `3dd7424e…`), router restarted, title-proxy restarted on both slots.
- Live: title-proxy-served viewer HTML contains the `_ghu` poller;
  `_landing_page()` render contains `ghPill` + poller (queue page served
  when no active slot — pill hidden by design).
- Behavior: grant/revoke now flips the top-bar pill within ~2 s, on the
  kiosk viewer and the landing page, without reload.
