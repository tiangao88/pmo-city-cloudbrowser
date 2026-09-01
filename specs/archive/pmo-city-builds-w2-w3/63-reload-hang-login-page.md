# 63 — Reload hang + PLEASE LOG IN: stale idle clock re-suspends woken slots (2026-08-25)

Status: **ROOT-CAUSED → FIXED → LIVE-VERIFIED** (commit `489700e`)

## Report (Tigo, 2026-08-25)

> "Recurring problem when I reload the URL cloudbrowser: it hangs forever.
> And I see again this neko login page which should never exist. And the
> way we use neko — sometimes the URL carries the user and the password.
> Is this a definitive constraint, can we remove it, does it impact the
> specs?"

## Root cause (live evidence)

The slot's **idle monitor uses the X server's idle clock, which does NOT
reset when Chrome starts**. Sequence observed live on slot-1:

```
10:54:24  SUSPEND (session ended — 15-min limit / idle)
10:55:52  wake → Chrome started (my direct wake)
10:56:26  SUSPEND again — 34 s later          ← stale X idle clock
```
and through the wake path directly:
```
11:02:18  chrome started
11:02:21  idle: SUSPEND — 3 s later           ← same root cause
```

After any idle/session-end, the freshly-woken slot still reports the
pre-wake X idle time (~20+ min) → the reaper believes the slot is idle →
suspends within seconds → the neko client that was auto-connecting loses
its WebSocket → the client (URL params already stripped after auto-login)
renders the **PLEASE LOG IN form** at the bare URL → the watchdog re-entry
or a reload hits the same race → **"hangs forever"**.

Note: a DIRECT slot wake (bypassing the router session state) additionally
gets fought by the router's own reaper (it doesn't know the user is
active). The real user flow (Open Browser → offer-take → router marks
active → wake) is the only valid path — verified below.

## Fix (restart-api.py, spec 63)

1. **`_wake_at` idle-baseline floor** — `do_wake` records `_wake_at =
   time.time()`; the reaper uses `max(last_activity(), _wake_at)` as the
   idle baseline. A freshly woken slot can never be suspended from a
   stale clock: it gets the full IDLE_TIMEOUT budget after every wake.
2. **Wake resets the activity markers** — touch `/tmp/cdp-activity`
   (cdp source) + set `_last_tab_activity = now` (tabs source) on wake.

## Live verification (through the real router path)

`GET /?pwd=neko&usr=…` (Open Browser click) → router offer-take → user
active (users {spike-user:1}) → slot woke → **Chrome RUNNING and held for
4+ minutes** (previously suspended within ~34 s). Harness 109/109.
Deployed to both slots.

## The neko usr/pwd question — definitive answer

- **Is it a definitive constraint? YES for neko 2.9.0 as shipped.** The
  neko client auto-connects (skips the login form) ONLY when the URL
  carries `?pwd=<NEKO_PASSWORD>&usr=<display name>` at load; the server
  additionally requires the password on the WebSocket upgrade
  (`/ws?password=`). There is no no-auth mode in the stock client/server.
- **Can we remove the user-visible requirement? YES — it is already
  internal.** The user never types or sees the credentials: the router
  injects them (landing "Open Browser" href, active-reload 302, queue
  `open_url`, watchdog re-entry). The login page should never appear; it
  appeared because of the suspend race above, not because the params are
  exposed.
- **Impact on specs: none required.** The `?pwd=&usr=` contract underpins
  specs 31 (entry), 39/40/54 (watchdog rescue), 48 (open_url/goto), 50
  (kiosk-open), 51 (identity) — all unchanged. Removing the params
  entirely would require a custom neko client build (W4+, not worth it).
- **One residual UX note:** the params ARE visible in the address bar
  during a session entry (they get stripped by the neko client after
  auto-login). If we ever want them fully hidden, a custom client build
  or a router-side cookie handoff would be the path — W4 candidate.

## Files

- `scripts/restart-api.py` (spec 63 idle floor)
- `specs/63-reload-hang-login-page.md`
