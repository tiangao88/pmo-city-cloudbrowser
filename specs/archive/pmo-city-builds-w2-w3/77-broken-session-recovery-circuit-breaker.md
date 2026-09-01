# Spec 77 — Broken-Session Recovery Circuit Breaker (cb-fleet-v2)

Status: **IMPLEMENTED — LIVE VERIFIED** (2026-08-28)

## 1. Problem

When a viewer session broke (neko stream wedged / login stuck), the page
watchdog called `/fleet/rescue` repeatedly. Beyond the per-session budget
(`CB_MAX_RESCUES`, spec 54) the router returned a **no-op** and left the
user **active** in `users`/`slots`/`sessions`. The client watchdog then
bounced to `/`, `/` saw the user still active and **302'd straight back
into the same wedged viewer** — a livelock that only the 60-min
max-duration reaper could break. Users saw "All browsers are in use" with
a misleading ETA while their broken session sat unusable.

Root cause (live evidence, 2026-08-27):
- `_rescue()` cap path (old): `200 {"action":"noop"}` — session untouched.
- The stream-dead branch in the page watchdog did **not** consult the
  `cb_rescues` budget (only the login-stuck branch did), so stream-dead
  could loop without ever exhausting the budget server-side.
- The viewer re-entry path never distinguished "active and usable" from
  "broken, awaiting recovery".

## 2. Design (decision memo, 2026-08-27; Tigo-approved)

Three layers, server-side circuit breaker as the safety boundary:

1. **App-level rescue (unchanged, kept first)** — `/fleet/rescue` →
   `supervisorctl restart neko` within the budget.
2. **Session-level circuit breaker (NEW)** — once the permitted rescues
   fail, the server must stop treating the assignment as active: mark a
   terminal reason (`stream_dead_cap` / `rescue_cap`), suspend the slot,
   archive with that reason, remove the user from
   `users`/`slots`/`sessions`, and free the slot for FIFO service.
3. **Explicit waiting/recovery state (NEW)** — `/fleet/my-status` reports
   `state=recovery` while the teardown is in flight and the archive reason
   afterwards; the root page serves the **queue page** for a quarantined
   user (never the viewer). A quarantined user can only re-enter by
   explicitly taking a fresh offer.

## 3. Implementation (commit `0a42fb9`)

`scripts/router.py`:

- `_rescue()` cap path: instead of `noop`, mark
  `_quarantined[email] = k`, `_quarantine_reason[email] =
  stream_dead_cap|rescue_cap`, `_expiring[email] = k`, then (outside
  `_lock`) call `_quarantine_suspend(email, k)` → POST slot `/suspend`
  with the terminal reason, and if the slot does not call
  `/fleet/release` back (legacy/ownerless slot or transient callback
  failure) **converge the router state** with an idempotent `_release`.
  Returns `200 {"action":"quarantine"}`. A repeated cap request after
  teardown gets `401` (no active session) — no restart, no resurrection.
- `_quarantine_suspend()` — network I/O happens **outside** `_lock` (the
  slot's suspend synchronously calls `/fleet/release` back into this
  router; holding the lock would deadlock the callback).
- `_release()` — preserves the quarantine reason (`stream_dead_cap` /
  `rescue_cap`), pops `_quarantined`/`_quarantine_reason`, and keeps the
  stale-notify guard (`had_assignment or had_offer or no archive yet`).
- `_resolve()` — a quarantine archive reason is **never auto-assignable**
  (`return None, False`), so a quarantined user surfaces a
  waiting/recovery state and can only re-enter by explicitly taking a
  fresh offer. `released`/`offer_expired` keep spec-41 FIFO semantics
  (auto-create only when no human is queued).
- `/fleet/my-status` — `state=recovery` while quarantined, archive reason
  afterwards; never `active`.
- Root handler — a quarantined/expiring user gets the **queue page**.
- Reaper force-release — preserves the quarantine archive reason.
- Watchdog JS (`_WATCHDOG`) — the **stream-dead** branch now consumes the
  same `sessionStorage['cb_rescues']` budget as login-stuck and, once
  exhausted, POSTs a terminal `reason:"stream-dead-cap"` to
  `/fleet/rescue` **before** bouncing to `/`.

## 4. Local regression suite

`scripts/test-router.py` — full router/watchdog/archive/queue harness.

- New circuit tests: cap → quarantine (user removed, archive
  `stream_dead_cap`), repeated cap request idempotent (401, no
  resurrection, no ghost queue entry), quarantined session not active,
  watchdog stream-dead budget/quarantine branch (scoped to the
  stream-dead block: terminal fetch precedes the root bounce).
- Spec-41 Exit-path test made race-free on slow hosts (waits for the
  async slot identify before the Exit click; long max session so the
  reaper cannot expire D mid-test — expiry is covered by earlier
  scenarios).

Result: **115 passed, 0 failed** (exit 0).

## 5. Deployment

- Target: **only** `cb-fleet-v2` (uuid `okixw2fxnwn1lakxvxajodww`,
  mother01). Router container `router-…` runs `python /app/router.py`
  from the shared `okixw2fxnwn1lakxvxajodww_scripts` volume.
- Deployed `router.py` to the scripts volume (uid 1000 / 0644), restarted
  only the router container. Slots / janitor / clamav untouched.
- SHA-256 (repo == volume == container `/app/router.py`):
  `5ee59ec787e368bf9dc76a008f0a752a70277abe9da76dd2697a915089e208e1`
- Pre-deploy hash: `cd9583bd0839113d746951c71aa603358faa2c0ea12c46e5addcb14b73f1d403`.
- Router boot: `v3 spec31: human_slots=1 agent_slots=1 human_max=60.0m
  agent_max=240.0m admin=[] agent_token=set` + `v3 on :8081, N_SLOTS=2`.

## 6. Live qualification (2026-08-28, PASS)

Controlled test on the **agent slot (slot-2)** so the user-visible human
queue and the active slot-1 session (spike-user) were untouched.

Sequence (live `CB_MAX_RESCUES` default 2, `CB_RESET_COOLDOWN_S=60`):

| Step | Call | Result |
|---|---|---|
| Assign agent to slot-2 | `POST /queue` (Bearer `CB_AGENT_TOKEN`, caller `d6-agent@aikumi.pro`) | `200 {status: active, slot: 2}` |
| Rescue #1 (stream-dead) | `POST /fleet/rescue` | `200 action=restart-neko` |
| Rescue #2 (after 61 s) | `POST /fleet/rescue` | `200 action=restart-neko` |
| Rescue #3 (after 61 s) | `POST /fleet/rescue` | `200 action=quarantine` |

Post-quarantine state (`GET /fleet/status`):
- `users = {"spike-user@aikumi.pro": 1}` — d6-agent removed.
- `archives["d6-agent@aikumi.pro"] = "stream_dead_cap"`.
- `queueDepth = {"human": 1, "agent": 0}` — human queue untouched
  (`montigaud@aikumi.pro/waiting` still present).
- Slot-2 freed.
- `GET /fleet/my-status` d6-agent → `state=stream_dead_cap` (not active).
- `GET /fleet/my-status` spike-user → `state=active` (slot-1 session
  unaffected through the router restart and the quarantine test).

**Result: PASS.**

## 7. Files

- `scripts/router.py` (modified), `scripts/test-router.py` (modified).
- Commit `0a42fb9` (pushed, `HEAD == origin/main`, tree clean).
