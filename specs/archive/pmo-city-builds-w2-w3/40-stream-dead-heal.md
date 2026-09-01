# 40 — Stream-Dead Neko Heal (blank-page wedge) — LOCKED design

**Status:** DONE 2026-08-22 — implemented & deployed (harness 75/75). Approved: Tigo chat ("yes do it") after the
second wedged-neko incident of the day.
**Incident (this spec's motivation):** montigaud@aikumi.pro logged into
CloudFiles fine but CloudBrowser hung on a **blank page**. Router OK
(302 into session), index OK (200 viewer HTML), WS OK (101), Chrome OK
(`cdp_ok: true`). Neko log showed the wedge: viewer connected 4:59PM →
`last listener, stopping` / `destroying session` 5:02PM → **then silence**:
neko kept accepting connections but never created a new session/capture
pipeline → no video stream → blank viewer. Manual `supervisorctl restart
neko` fixed it instantly (Chrome/profile/tabs untouched).

Spec 39's watchdog only detects the *LOG-IN stuck* wedge (login screen
visible AND `?pwd=` never stripped). This is a different symptom of the
same family: **neko accepts connections but never restarts its session
pipeline** — no login screen, so spec 39 never fires.

## 1. Detection — two layers

### 1.1 Client watchdog v3 (router-injected, in the viewer page)

The neko client renders the stream in `<div class="player-container">
<video ref="video" playsinline>`. The client has **no
visibilitychange/pause handlers** — a live stream keeps `currentTime`
advancing even in a background tab, so a stalled playhead is a reliable
dead-stream signal.

In the existing 2s watchdog poll, when NOT on the login screen:

- **Stream present (`video` found):** track `video.currentTime`. If it
  fails to advance for `CB_STREAM_AFTER` consecutive polls (or
  `readyState < 2` for the same window — no frames ever arrived) → dead
  stream → `POST /fleet/rescue {reason:"stream-dead"}` + bounce to `/`.
- **Neither login screen nor video found for the same window:** the
  viewer app never reached a functional state (blank-page case (b)) →
  same escalation. The boot window is ~seconds on the LAN; the default
  20 s window makes false positives unlikely, and a false rescue only
  costs a neko app restart (~2 s, tabs preserved).

Reuses the spec-39 machinery end-to-end (`/fleet/rescue` → slot
`/restart-neko` → `supervisorctl restart neko`), so a stuck client and a
blank-page client both converge on the same rescue path.

### 1.2 Server backstop (restart-api `stream_guard_loop`)

Heals the slot **before** the next login even when no viewer is open:

- Pure check `neko_wedged(log_path, guard_s)`: the **last non-empty line**
  of `/var/log/neko/neko.log` matches the teardown pattern
  (`destroying session` / `last listener, stopping`) AND the file has not
  been written for > `CB_STREAM_GUARD_S` (default 90 s).
- Guard thread (10 s cadence): only when the slot is **occupied**
  (`slot_user()` set) and **not suspended** (reaper owns idle slots).
  On match → `restart_neko()` (same cooldown as `/restart-neko` via
  `_rescue_last`, so max ~2 restarts per episode) + counts a `heals`
  counter surfaced in `/health`.
- Healthy active viewer: last log lines are session-start/ICE activity —
  no match. Healthy closed tab: slot goes idle → reaper suspends before
  the guard window matters; a neko restart on an unviewed occupied slot
  is harmless anyway (app-only, Chrome untouched).

## 2. Envs

| Env | Where | Default | Meaning |
|---|---|---|---|
| `CB_STREAM_AFTER` | router (watchdog JS) | 10 | consecutive 2 s polls with stalled/absent stream before rescue |
| `CB_STREAM_GUARD_S` | slots (restart-api) | 90 | seconds of post-teardown log silence on an occupied slot before auto-restart |

## 3. Files

- `scripts/router.py`: watchdog v3 stream-dead block (`__STREAM_AFTER__`
  interpolation), `/fleet/rescue` accepts `body.reason` (`login-stuck`
  default / `stream-dead`), `rescue_at[email]` becomes
  `{ts, reason}`, `/fleet/status` surfaces it.
- `scripts/restart-api.py`: `neko_wedged()` pure fn, `stream_guard_loop()`
  thread, `heals` in `/health`, reuses `_rescue_last` cooldown.
- `scripts/test-router.py`: watchdog-JS stream block + interpolation
  checks; rescue-with-reason checks.
- `26-s7-fleet-compose-v2.yaml`: env rows.

## 4. DoD / acceptance

1. [x] Harness green: 75/75 (baseline 70 + 5 spec-40 checks: rescue
   reason plumbing + watchdog v3 JS embed/interpolation).
2. [ ] Client E2E: with a live slot, kill the neko capture (or hold the WS
   so a session can't start) → viewer self-rescues to a working stream
   within ~CB_STREAM_AFTER × 2 s + reload, no human. — **pending live
   soak** (no active user at deploy time; code path covered by harness).
3. [ ] Server E2E: on an occupied slot, truncate neko.log to a lone
   teardown line with old mtime → guard restarts neko within one cadence;
   `/health` shows `heals` incremented. — **pending live soak** (guard
   observed started on both slots; fire path covered by unit design).
4. [ ] No regression: healthy viewer never rescues (currentTime
   advances); idle slots unaffected (reaper owns them). — pending soak
   through normal use; assignment-duration condition added to close the
   assignment→viewer-connect false-fire gap.

## 5. Prevention (root cause) — follow-ups

- **Primary: upgrade neko image 2.9.0 → latest 2.x** — the
  teardown→restart-never class of pipeline bugs has upstream fixes.
  Requires a fleet image swap (both slots recreate; needs Tigo-approved
  maintenance window). This spec's auto-heal is the stopgap.
- **Monitoring:** rescue reasons (`login-stuck` / `stream-dead`) and
  `heals` counters are now visible in `/fleet/status` + `/health` — add
  to the D9 soak daily digest so a wedge pattern is visible over time.
- **Rejected: session keep-alive peer** — a synthetic WS viewer holding
  the session open keeps the 1280×720@30 encode running while idle
  (CPU/waste), and the wedge can still occur on the first connect.
