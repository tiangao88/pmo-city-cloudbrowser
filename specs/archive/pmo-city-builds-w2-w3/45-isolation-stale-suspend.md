# Spec 45 — Isolation Breach: stale-suspend no-op + offer-take without wake

**Status:** ✅ DEPLOYED + verified (fleet cb-fleet-v2, commit `f19a10c`)
**Date:** 2026-08-22
**Severity:** HIGH — cross-user session exposure (3rd occurrence, spec 41/43 class)
**Component:** `restart-api.py` (slot agent), `router.py` (fleet router)
**Reporter:** Tigo (spike-user@aikumi.pro saw montigaud@aikumi.pro's live session)

---

## TL;DR

A slot that was left in a stale **`_suspended=True`** state silently ignored the
reaper's suspend calls (returned 200 without acting), so when the router
force-released the slot and offered it to the next user, the **take path proxied
the browser without waking/swapping** — handing the new user the **previous
user's live Chrome profile** (tabs + SSO cookies). Root trigger: the Chrome
start that left the slot stale bypassed `/wake` (the spec-40 rescue / manual
`supervisorctl start` path).

## Timeline (2026-08-22, all UTC)

| Time | Event |
|---|---|
| 20:26 | spec-40 stream-dead rescue: neko restarted (slot-1) |
| 20:44:55 | idle-suspend: archived montigaud, `_suspended=True`, Chrome stopped |
| ~21:07 | **manual `supervisorctl start google-chrome` (agent black-screen fix) — bypasses `/wake`, `_suspended` stays `True`** |
| 21:07:09 | Chrome up, montigaud profile restored from archive (PMBOK tab), but `_suspended=True` stale |
| 21:17:25 | montigaud TTL expires → reaper `POST /suspend` → **slot returns 200, does NOTHING** (`if _suspended: return`) |
| 21:17:35 | reaper suspend retry → 200, no-op again |
| 21:17:45 | reaper: **force-release montigaud** (release not received in 20s) → archive reason=expired (mtime unchanged: **20:44**) |
| 21:17:54 | router offers slot-1 to spike-user (queue head); spike-user takes → **router proxies browser directly — NO `/wake`, NO ownership check** |
| 21:18+ | spike-user sees **montigaud's live Chrome**: PMBOK tab + montigaud's SSO cookies, bar labeled spike-user |
| 21:24 | agent repairs: stop Chrome, wipe live profile, restart restart-api (clears stale flag), fresh Chrome → spike-user clean |

## Root cause (two compounding holes)

### Hole 1 — stale `_suspended` silent no-op (restart-api.py)

`do_suspend()` starts with:

```python
if _suspended:
    return            # <-- silent 200, NO teardown
```

`_suspended` is set `True` by the idle/reaper suspend, and reset **only** by
`do_wake()`. Any Chrome start that bypasses `/wake` leaves the flag stale:

- agent `supervisorctl start google-chrome` (this incident),
- spec-40 rescue restarting neko without re-arming Chrome (the black-screen
  incident, same session),
- any manual container-exec start.

Result: the reaper's suspend POSTs return 200 (router believes the slot is
suspended) while Chrome **actually keeps running** with the old user's live
profile.

### Hole 2 — offer-take proxies without waking (router.py)

The offer-take path (`offer taken by <user> → slot-1`) does **not** call
`/wake` on the slot, and does not verify the slot's actual state (e.g.
`suspended: true` from `/health`). It trusts that the reaper already suspended
the slot. When Hole 1 makes that trust false, the take hands over a **live
foreign session**.

### Contributing factor

The spec-40 rescue restarts neko but does **not** re-arm Chrome (leaves it
STOPPED). That forced the manual Chrome start in the first place.

## Fixes (hotfix — this spec)

1. **`do_suspend()`: trust process reality, not the flag.** Replace the
   flag-only early return with: if `_suspended` AND chrome is not actually
   running → safe no-op (return). If `_suspended` AND chrome IS running →
   proceed with teardown anyway (stale flag, still must suspend).
2. **Offer-take: verify/wake before granting.** Before the router hands a slot
   to the next user on an offer take, call the slot's `/health` (or `/wake`)
   and ensure the slot reports suspended/no running Chrome. If Chrome is
   running for another user, refuse the take (queue stays) and log loudly.
3. **Boot/reconcile `_suspended`:** on `restart-api` boot and on any Chrome
   process start observed by the watchdog, reconcile the flag with actual
   process state (if chrome running and not intended → the flag must not
   suppress suspend).

## Verification

- Harness: new test — stale `_suspended` with Chrome running → `/suspend`
  still tears down (Chrome stopped, archived, release called).
- Router test: take path calls `/health` (or `/wake`) before granting; a slot
  reporting chrome-running-for-other-user → take refused.
- Live: force the stale-suspend state, run reaper suspend, confirm teardown;
  then take path, confirm isolation.

## Fixes deployed

- **Commit `f19a10c`** (2026-08-22): router.py + restart-api.py + test-router.py
  synced to repo and pushed. Harness **92/92 PASS** (deterministic spec45 block:
  FakeSlot GET `/health` + `stale_suspend` mode — A expires → stale suspend → B
  take **REFUSED** (queue page, not landing) → B re-offered once slot genuinely
  clean → B active).
- **Fleet deploy (cb-fleet-v2, mother01):**
  - `router.py` → shared scripts volume (md5 verified live, `_slot_clean` guard
    present at running-container lines 729/1299). Router container restarted
    healthy.
  - `restart-api.py` → shared volume **byte-for-byte** (md5
    `f7317c77f2fe7b04fc58f52effde94b6`, 55420 B; scp silent-failure pitfall —
    re-uploaded via `cat | docker run alpine` pattern). Both slots' restart-api
    processes restarted.
  - **Live proof:** during the restart window (slot 9230 not yet bound) the
    guard failed closed — router log:
    `slot-1 health check failed: Connection refused — treating as NOT clean` →
    `take REFUSED slot-1 for montigaud@aikumi.pro: slot not clean (chrome
    running?) — keeping offered`. montigaud stayed queued; no foreign session
    handed over.
  - Post-bind `/health` from inside router: slot-1 `suspended: True`,
    `user: spike-user2@aikumi.pro`; slot-2 `suspended: True`,
    `user: spike-user@aikumi.pro` (both Chrome STOPPED, `cdp_ok: False`) —
    clean takes pass, stale ones refused.

## Related

- spec 41–43 (cross-user session leak, wake-storm, isolation suite T1–T10)
- spec 40 (stream-dead rescue — restarts neko, must re-arm Chrome)
- W3 FIRST item: deferred isolation tests T6/T8/T9 + full T7 marker-tab replay
  — **would have caught this**; pull forward.
