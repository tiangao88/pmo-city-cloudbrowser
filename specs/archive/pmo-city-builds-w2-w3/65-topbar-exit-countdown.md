# 65 — Top-bar Exit (right of email) + session countdown in the neko top bar (2026-08-25)

Status: **IMPLEMENTED → DEPLOYED → LIVE-VERIFIED** (harness 114/114, timer/MFA regression 8/8, commit `c7be45e`)

## Request (Tigo, 2026-08-25)

> "The exit button is not in the top bar, top right, next to the email.
> It is in the tab bar at bottom right. Have a look. And yes, implement
> the countdown immediately and document all of that."

## Architecture finding — why the Exit was never in the user's top bar

The top bar the user sees (CloudFiles | 🔒 Secrets | 🔗 Shared | email)
is the **neko CLIENT page bar**, injected by **title-proxy** into the
served neko index (`ul.menu`). It renders in the USER'S own browser
(and, transiently, in the kiosk's first tab).

The tab-bar extension (content.js) runs **only inside the kiosk Chrome**
(`--load-extension`). Its spec-41 `ensureBarExit()` injects into
`ul.menu` **of the kiosk's own client-page tab only** — that page is not
normally present (the user navigates to external sites), and the
extension never runs in the user's browser. So the spec-62 verification
("exitLi true in ul.menu") observed the kiosk's own client tab, NOT the
steady user view. **The top-bar Exit was effectively absent for the
user** — the only always-visible Exit was the tab-bar fallback
(v1.13.x), bottom-right, exactly as Tigo reported.

**Conclusion:** the top bar is title-proxy territory; the extension
cannot reach it in the user's browser. Both the Exit and the countdown
must be injected by **title-proxy** and drive the **router**.

## Implementation

### title-proxy.py — injected top-bar script (client page)
- **Exit button** (`⏏ Exit session`, red-tinted pill) inserted **right
  of the email** (`eml.insertAdjacentElement('afterend', …)`, DOM order
  email → Exit → countdown). Two-step confirm: first click arms
  ("Release? ✓", auto-disarm 6 s), second click POSTs
  `/session/release` (same-origin router, tinyauth cookie +
  Remote-Email), then polls `/queue/status` until status != active and
  redirects to `/`. Idempotent (`cb-exit-li` guard) — the extension's
  `ensureBarExit()` uses the same class, so whichever injects first
  wins, no duplication on the kiosk's client tab.
- **Countdown** (`⏳ mm:ss`, amber) right of the Exit: polls
  `/queue/status` every 15 s (cache:no-store) for `session_ttl_s`,
  ticks locally every 1 s; hidden when not active. Same data the queue
  page already uses (spec 31) — `CB_HUMAN_MAX_SESSION_MIN`-derived.
- Both re-applied by the existing `ap()` MutationObserver (Vue
  re-renders), live-flip poll untouched.

### router.py — `POST /session/release`
- Dispatched in `_route()` **before human-entry logic** (same trust
  shape as `/fleet/rescue`): Remote-Email required (401), active
  session required (400), then forwards to the owner slot's
  restart-api `/release` (`http://slot-<k>:9230/release`, 8 s timeout;
  502 on failure). The slot owns the teardown (snapshot → archive →
  wipe → notify `reason=released` → router pops state + re-queues
  FIFO, spec 41 semantics). A release can never target a different
  user's slot.
- Dead block removed from `_fleet_post` (that dispatcher only runs
  WITHOUT Remote-Email).

## Verification

- **Harness 114/114** (109 + 5 new spec-65 checks): re-enter A →
  POST `/session/release` with email → 200 → notify lands → archived
  `reason=released`, slot freed; no Remote-Email → 401; unknown user →
  400.
- **Live:** router endpoint 401 without Remote-Email; served session
  page contains `cb-ttl-li` + `cb-exit-li` + `/session/release` + the
  countdown poll (slot-1, both slots' title-proxy restarted, md5
  verified). Full user click = Tigo's next session (not triggered on a
  live session by the agent).
- Note: `s%60` must stay `s%%60` in the Python source (the script is a
  %-format string) — broke title-proxy with "not enough arguments for
  format string" on first deploy, fixed and redeployed.

## Files

- `scripts/title-proxy.py` (top-bar Exit + countdown injection)
- `scripts/router.py` (`/session/release`)
- `scripts/test-router.py` (spec-65 tests)
- `specs/65-topbar-exit-countdown.md`

## Follow-ups

- The tab-bar Exit fallback (v1.13.1) stays for external pages (no
  neko top bar there) — two affordances, complementary surfaces.
- Countdown is based on the configured `CB_HUMAN_MAX_SESSION_MIN` limit. The
  live spec-65 smoke observed the deployed 60-minute human limit via the router
  boot configuration and the active-session TTL field; it does not alter the
  session limit itself.
- spec 62's "verified live in ul.menu" note is corrected here: that
  verification observed the kiosk's own client-page tab, not the
  user's browser view.
