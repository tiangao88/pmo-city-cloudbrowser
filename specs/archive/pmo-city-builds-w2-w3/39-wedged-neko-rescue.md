# 39 — Wedged-Neko Auto-Rescue (LOCKED design)

**Status:** IMPLEMENTED + DEPLOYED — 2026-08-22 (same-day implementation on
Tigo's go). Harness **70/70 green** (59 baseline + 11 spec-39 checks); code
live on the fleet (router + both slots); restart-api guards live-verified
(409 conflict / 200 matching owner / 429 cooldown).
**Design:** locked 2026-08-22, Tigo chat approval ("Yes make the specs",
alongside his full cb-fleet app restart).

## 0. Implementation notes (2026-08-22)

- Watchdog v2 (router `_WATCHDOG`) counts consecutive stuck polls
  (`loginScreen()` true AND `?pwd=` still present → auto-login failed);
  after `CB_RESET_AFTER` (10 × 2 s) it POSTs `/fleet/rescue` and bounces
  to `/`. Client cooldown `CB_RESET_COOLDOWN_S` + server cooldowns on both
  router and restart-api ⇒ escalation ceiling ≈ 2 rescues per episode.
- Router `_rescue()`: locates the caller's slot from the users map, POSTs
  `http://slot-<k>:9230/restart-neko`, records `rescue_at[user]` on success
  (no cooldown recorded on failure → retry allowed), returns 401 (no
  session) / 429 (cooldown) / 502 (slot unreachable or refused).
- restart-api `/restart-neko` (live-verified): the router's users map is
  authoritative — a **conflicting** local slot owner → 409; both absent →
  409 idle; else `supervisorctl restart neko` (app only), 429 within
  cooldown, 502 on supervisor failure.
- **Pitfall found live:** slot `.slot-user.json` goes stale when a router
  restart interrupts an offer (`identify slot-1 failed: timed out`), and
  the identify sweep only re-pushes on email *change*. The owner-conflict
  rule above keeps rescue correct anyway; stale files are dormant for
  rescue (router only calls the slot its map points to). Manual identify
  pushes must mirror the CURRENT `/fleet/status` users map (slot ownership
  shifts during fleet restarts — pushing from a stale snapshot overwrites
  the right owner; happened once during deploy, caught and fixed).
- `_pipe_injected` (raw-proxy fallback) interpolates the rescue envs into
  the watchdog JS it embeds, same as the direct injection path.

## 1. Incident (2026-08-22, slot-1)

A viewer on `montigaud@aikumi.pro`'s slot was stuck on the neko **LOG IN**
screen. Chrome was freshly started and the router was serving the neko index
+ watchdog; the router log showed the viewer WS upgrade
(`GET /ws?password=neko`) being proxied — yet the member session never
formed and the LOG IN persisted. A full container restart (fresh neko +
Chrome + restart-api) cleared it immediately; the slot had previously been
handed over from a reaper-expired session to the queue head.

**Root cause:** the neko server process had been up **3h14m**; its
member/WebSocket auth state wedged after the session handover. It kept
serving the SPA and accepting the proxied WS path, but no viewer could
authenticate. This is the one state the existing watchdog cannot clear:

- The watchdog (router `_WATCHDOG`, spec 31 §9) re-enters the session via
  `?pwd=&usr=` **only when** `location.search` has no `pwd=` (guard at
  router.py L417: `loginScreen() && location.search.indexOf("pwd=") === -1`).
- On a *successful* auto-login neko strips the params, so the guard is
  correct for healthy drops.
- On a *wedged* auto-login neko never strips the params → the guard stays
  false forever → **the watchdog gives up after exactly one re-entry** and
  the LOG IN sticks until a human restarts the container.

## 2. Design (two escalation layers)

Never show the neko LOG IN holds for in-flight sessions too. When re-entry
fails, we don't just sit there — we **rescue the neko app process**.

### Layer 1 — Watchdog escalation (client, `_WATCHDOG`)

- Track a **stuck counter**: consecutive polls where
  `loginScreen()` is true AND `location.search` contains `pwd=`
  (re-entry was attempted but auto-login never succeeded — neko did not
  strip the params).
- After `RESCUE_AFTER` consecutive stuck polls (default **10** × 2 s =
  20 s), `fetch("/fleet/rescue", {method:"POST"})`, then bounce
  `location.href = "/"` (the router re-serves the session once the slot
  recovers). Reset the stuck counter on success or on any poll where the
  LOG IN is gone.
- **Cooldown:** never issue a rescue more often than `RESCUE_COOLDOWN_S`
  (default **60 s**); tracked client-side in a timestamp and enforced
  server-side too (Layer 3). Prevents a wedged-but-slow slot from being
  thrashed.

### Layer 2 — Slot neko restart (server, restart-api)

- New route `POST /restart-neko`:
  - **Auth:** same discipline as `/release` — user derived from the slot's
    `.slot-user.json`; a requester cannot target another owner. Body
    `{requester: "watchdog"}`.
  - **Action:** `supervisorctl restart neko` — restart the **neko app
    process only**, never the container, never Chrome. This is the key
    property: the profile, open tabs, and Chrome stay untouched; only the
    wedged WebRTC/auth server is recycled (~seconds).
  - **Guardrails:** refuse with 409 if no active slot user (idle slot —
    idle-suspend owns that state, nothing to rescue). Refuse with 429 if a
    rescue ran < `RESCUE_COOLDOWN_S` ago (rate limit).
  - Returns `{ok: true, restarted_at}`.

### Layer 3 — Router coordination (`/fleet/rescue`)

- New endpoint `POST /fleet/rescue`:
  - **Auth:** `Remote-Email` must be the current active user on a slot
    (same gate as everywhere else) → else 401.
  - **Action:** `POST http://<slot>:9230/restart-neko` with the user's
    email; wait ≤ 5 s.
  - Returns `{ok, user, action: "restart-neko", slot}` on success;
    `{ok: false, error}` if the slot is unreachable (the watchdog's
    bounce-to-landing still gives a clean surface; the reaper/self-heal
    path already covers dead slots — no rescue needed there).
  - **Log:** `[router] rescue user=<email> slot=<k> → restart-neko`
    (idempotent, auditable).
  - **State:** router persists `rescue_at[user]` for the server-side
    cooldown; exposed in `/fleet/status` as `rescues` for observability.

### Escalation ceiling

Max **2 rescue attempts** per stuck episode, then stop and surface an
alert (router log + `rescues` counter) instead of auto-nuking the
container. A still-stuck session after 2 app restarts is a new incident
class (e.g. full-container restart, which the ops human owns). We never
auto-restart containers from the watchdog path.

## 3. Why app-level, not container-level

| | neko app restart | container restart |
|---|---|---|
| Fixes wedged member/WS auth | ✅ (root cause) | ✅ |
| Preserves Chrome profile + tabs | ✅ | ❌ (fresh Chrome, re-restore) |
| Downtime | ~seconds | ~10–20 s + restore |
| Risk to other programs (title-proxy, restart-api, openbox) | none | full bounce |

Container restart stays the human escalation; app restart is the automatic
one.

## 4. Configuration (compose envs, defaults)

| Var | Default | Meaning |
|---|---|---|
| `CB_RESET_AFTER` | `10` | stuck polls (×2 s poll) before rescue fires |
| `CB_RESET_COOLDOWN_S` | `60` | min seconds between rescues (client + server) |

## 5. Files

- `scripts/router.py`: `_WATCHDOG` v2 escalation block, `POST /fleet/rescue`
  handler + `_rescue()` (users-map lookup, slot POST, `rescue_at` in router
  state, 401/429/502), `/fleet/status` gains `rescues`.
- `scripts/restart-api.py`: `POST /restart-neko` route (`supervisorctl
  restart neko` — app only, owner-conflict + idle + rate-limit guards).
- `scripts/test-router.py`: harness — fake-slot `/restart-neko`, `/fleet/rescue`
  auth/cooldown/failing-slot/retry, `rescues` observability, watchdog JS
  escalation + interpolation, no-regression 59/59 baseline.
- `26-s7-fleet-compose-v2.yaml`: the two env rows (router: both; slots:
  `CB_RESET_COOLDOWN_S`).

## 6. DoD / acceptance

1. **Harness:** spec-39 tests pass on top of the 59/59 baseline — **done
   2026-08-22: 70/70** (rescue fires once per episode; cooldown respected;
   401 non-owner; failing slot → 502 then retry; idle slot refuses).
2. **Live pilot (with Tigo):** with an active session on a LOG IN, run
   `docker exec <slot> supervisorctl restart neko` from the host while the
   viewer is stuck → the watchdog rescues and the session restores within
   ~30 s, **without** a container restart and without losing Chrome tabs.
   — *pending (needs a wedged session or a scheduled drill).*
3. **No regression:** the whole harness stays green; router
   `/fleet/status` healthy after deploy. — **done 2026-08-22** (70/70;
   live `/fleet/status` shows `rescues`, fleet serving normally).
4. **Containers never auto-restarted** by this path; escalation ceiling =
   2 rescues then alert.
