# Spec 54 — Cap the login-stuck rescue loop (per-session escalation budget)

> **Status: DONE (2026-08-24).**
> Trigger: Tigo got the neko "PLEASE LOG IN" screen again — the page
> auto-reloaded repeatedly. Router logs showed the watchdog escalated
> `rescue → restart-neko` **twice** under spike-user's active session.

## 1. Root cause

The watchdog (spec 39/40) escalates a wedged neko login by POSTing
`/fleet/rescue` → slot `restart-neko`. The docstring claimed a "2 rescue
attempts per episode" ceiling — **the client had no such cap**: each
rescue reloads the page, `stuck` resets to 0, and the login-stuck
condition re-accumulates → restart-neko again after every cooldown
window (60 s). An unbounded restart loop under an active user; the
"auto-reload to PLEASE LOG IN" the user saw is the neko app restarting
under them. (The session then expired into the queue — montigaud took
the slot, the stale viewer tab could not recover on its own.)

## 2. Fix

**Client (watchdog JS in router.py):**
- `sessionStorage['cb_rescues']` counts login-stuck escalations **per
  session** (survives the rescue reloads).
- Beyond `CB_MAX_RESCUES` (default **2**), the watchdog stops calling
  rescue and just re-entries (`location.href = "/"`).
- Budget resets automatically on a healthy session (login screen gone →
  `sessionStorage.removeItem('cb_rescues')`).

**Server (`_rescue` in router.py):**
- `rescue_at[email]` records `n` (count); when `n >= CB_MAX_RESCUES`
  the endpoint returns `200 {"action": "noop"}` — **no restart**, session
  untouched. Fail-closed even if a stale/foreign page keeps calling.
- Budget resets on every new session: wake/assign/offer-take/agent
  instant-assign all `pop("rescue_at", email)`.
- Env: `CB_MAX_RESCUES` (default 2; tests raise it for the classic
  spec39/40 escalation coverage).

## 3. Verification

- Harness: **109/109 PASS** (103 previous + 6 new spec-54 checks:
  first rescue → restart; second → noop; still capped; session
  unaffected; `n` recorded).

## 4. Why noop-and-let-expire is correct

The reaper still ends the session at `CB_HUMAN_MAX_SESSION_MIN`; the
user lands on the queue page with a clean re-entry path. Restarting neko
under a wedged client only burns cycles and produces the scary
auto-reload. A *real* wedge eventually clears on the next clean take
(restart-api restarts neko on wake anyway).
