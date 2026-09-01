# Spec 46 — Offer-take never wakes Chrome + dirty freed-slot wedge

**Status:** ✅ DEPLOYED + verified (fleet cb-fleet-v2, commit `596bb72`)
**Date:** 2026-08-22
**Severity:** HIGH — every offer-take since spec 42 handed the user a slot with
no Chrome (neko UI only); a dirty freed slot wedged the fleet forever
**Component:** `router.py` (fleet router), `test-router.py` (harness)
**Reporter:** Tigo (montigaud@aikumi.pro clicked "Open Browser", got no browser)

---

## TL;DR

Two related router bugs, both surfaced live by montigaud's take on 2026-08-22:

1. **The take path never woke the slot.** Spec 42 removed the offer-time
   pre-wake (it caused a wake storm / profile swap under a live Chrome) and the
   comment said "the take path wakes it" — but the take path still hardcoded
   `woke = False` (pre-existing since `a6b8ef0`). So every offer-take since
   spec 42 handed the user a **suspended slot**: neko UI loads, WS connects,
   but `google-chrome: STOPPED`, `cdp_ok: false`. montigaud hit this live.

2. **A dirty freed slot wedged the fleet.** When a slot was freed without its
   Chrome actually stopping (force-release self-heal, or a
   release-without-teardown), the spec-45 take-time guard (`_slot_clean`)
   correctly refused the take — but nothing ever cleaned the slot, so every
   subsequent offer→take→refuse looped forever. One permanently dead slot.

## Root cause

### Bug 1 — `woke = False` on the take path (`router.py` ~L1318)

- Spec 42 (commit `6e6fb7e`) removed the offer-time pre-wake
  (`_offer_wake` dead code). Reaper comment: *"NO pre-wake at offer time. The
  slot stays suspended until the offer is TAKEN — the take path wakes it."*
- **But the take path was never updated** — it hardcoded `woke = False`
  (pre-existing since `a6b8ef0`). The wake block lives only in the
  `_resolve()` branch. So a taken offer granted the slot, proxied the neko UI,
  and never started Chrome.
- `git blame` trail: `a6b8ef0` (introduced `woke=False` on take) →
  `6e6fb7e` (removed the pre-wake, left the take broken).

### Bug 2 — no self-heal for a dirty freed slot (`_reaper_loop` offer leg)

- The reaper force-release (self-heal) frees a user while the slot may still
  have Chrome running for them (the spec-45 incident class).
- The offer leg then offered that slot; the take-time `_slot_clean` guard
  (spec 45) refused — correct isolation, but nothing re-suspended the slot,
  so it was refused at every take forever.

## Fixes

### Fix 1 — take wakes the slot (`router.py`, offer-take branch)

The take path now explicitly calls `_wake_slot(k, email)` after `_slot_clean`
proved the slot genuinely suspended. On wake failure the grant is rolled back
(re-archive reason=idle, reaper re-offers). No wake-storm risk: the wake
happens once, at take-over, on a slot that was just verified suspended.

### Fix 2 — reaper self-heal sweep (`router.py`, offer leg)

The offer leg is now two-phase:

1. **Phase A (under lock, pure state):** gather candidate `(slot, entry)` for
   free slots with waiting queue heads.
2. **Phase B (outside the lock):** for each candidate, verify the slot's
   restart-api `/health` reports `suspended: true`. If dirty → `POST /suspend`
   (self-heal — with the spec-45 restart-api fix a /suspend on a live-Chrome
   slot now force-tears-down and converges) and skip offering this tick.
3. **Phase C (under lock, re-verify):** commit the offer only if the slot and
   entry haven't moved.

Network calls stay outside `_lock` so the router never blocks on a slot. The
spec-45 take-time `_slot_clean` guard remains as the isolation backstop for the
race where a slot dirties between offer and take.

## Tests

`test-router.py` restructured (94/94 PASS):

- `spec46: take woke the slot (chrome running)` — the spec-45 block's final
  take asserts `wakes >= 1` and `chrome_running is True`.
- `spec46: A force-released (stale latch → no release callback)` — waits for
  the reaper force-release, not the (never-arriving) offer.
- `spec46: dirty slot NOT offered (self-heal re-suspends)` — asserts B stays
  "waiting" over a window and that the reaper's self-heal fired a `/suspend`.
- `spec45: B offered once slot genuinely suspended` / take REFUSED while
  re-dirtied / active once clean — the isolation backstop still verified.

## Deployment (cb-fleet-v2, mother01)

- `router.py` written to shared scripts volume (md5 `c9ace35798b7e394b0d7f0c18506bd36`
  verified local↔remote), router container restarted, state intact.
- Live proof: `spike-user@aikumi.pro` was hit by Bug 1 (slot-1
  `google-chrome: STOPPED`, `cdp_ok: false`); manual `POST /wake` →
  `suspended: false`, `cdp_ok: true`, `google-chrome: RUNNING` — the same
  rescue the take path now performs automatically.

## Follow-up

- D15C restart-recreate resilience and the W3 isolation deferred tests
  (T6/T8/T9, full T7) remain the durable coverage for this incident class.
