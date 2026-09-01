# Spec 29 — Idle suspend/resume for the cloud-browser fleet (W2)

**Status:** APPROVED (Tigo 2026-08-21) — design + Coolify variable defaults.
**Scope:** freeing cloud-browser sessions that are idle so waiting humans
don't hit a 503, while preserving the exact session state for resume —
for **human** (neko viewer) and **AI-agent** (CDP) users alike.
**Depends on:** spec 26 (S7 fleet), spec 27 (tabbar limit), W2 DoD item
"idle-stop refinement".

## 1. Problem

- Browsers are a scarce shared resource (2 slots today, cap by
  `MAX_RUNNING_BROWSERS`).
- Today a stickied user **never** releases a slot: `last_seen` is
  recorded per request but **never read** (router-v2.py) — an idle user
  blocks a waiting one until a crash or a manual container restart.
- Goal: after a configurable idle period, **suspend** the session —
  free the resources AND the slot for the next human — and **resume it
  later from the exact same status** (cookies, logins, tabs, downloads).

## 2. Current persistence (verified in compose v2)

| Volume | Mount | Holds | Bound to |
|---|---|---|---|
| `slot-1-profile` | `/home/neko/.config` | Chrome profile | slot-1 |
| `slot-2-profile` | `/home/neko/.config` | Chrome profile | slot-2 |
| `slot-1-downloads`/`slot-2-downloads` | `/home/neko/Downloads` | files | slot |
| `router-state` | `/data/state` | sticky map | — |
| `scripts` | supervisord dirs | code | — |

Key insight: persistence is **per-slot, not per-user**. Releasing a slot
requires decoupling user state from the slot volume — the archive below.

## 3. Activity model — humans AND agents

A session is **active** if ANY configured source reports activity; else
idle. Agent (CDP) activity is essential: an AI agent must not be
suspended mid-task, and a *stuck* agent (sends nothing) must be freeable.

| Source | Human (neko) | Agent (CDP) | Mechanism |
|---|---|---|---|
| X11 input idle | ✅ | ❌ never fires (CDP input bypasses X) | `xprintidle` / python-xlib on slot display |
| WebRTC media connected | ✅ | only if human watches | neko peer state |
| Tab/navigation diffs | ✅ | ✅ | restart-api tab snapshot (already 30 s) |
| Router `last_seen` | ✅ | ❌ (agent bypasses router) | per-request touch (already exists) |
| **CDP relay commands** | n/a | ✅ **the agent signal** | relay timestamps client→browser commands |

Unified rule: `active = human_active OR agent_active`. Agent signal =
"cdp-relay forwarded a client→browser command within the window"
(relay already proxies every command; add a timestamp, zero client
changes).

## 4. Coolify environment variables (defaults APPROVED by Tigo)

| Variable | Default | Meaning |
|---|---|---|
| `IDLE_TIMEOUT_MIN` | `15` | allowed idle before suspend |
| `IDLE_GRACE_MIN` | `5` | toast warning before suspending ("Session idle — suspends in 5 min") via existing tabbar plumbing |
| `IDLE_CHECK_INTERVAL` | `60` | reaper cadence (s) |
| `IDLE_ACTIVITY_SOURCES` | `xinput,media,tabs,cdp` | which signals count as activity |
| `IDLE_ACTION` | `suspend` | what happens at timeout (suspend only for now) |

All `${VAR:-default}` in compose, per convention.

## 5. Lifecycle

```
active ──(idle ≥ IDLE_TIMEOUT_MIN)──▶ grace ──(IDLE_GRACE_MIN)──▶ suspend
  ▲                                                                  │
  │ activity (any source) resets timer                               │
  └─────────────── resume on next request (user or agent) ◀──────────┘
```

- **Suspend:** stop Chrome (supervisorctl) → archive state → release
  sticky (`/fleet/release`) → slot serves the next human with a fresh
  profile.
- **Grace:** tabbar toast via `TAB_EVICTED`-style plumbing (reuse the
  toast channel); activity during grace cancels.
- **Resume:** router sees a request from a user with an archive → restore
  archive onto any free slot (fresh profile dir ← archive contents) →
  start Chrome → restore tabs from snapshot → serve. Same user returns to
  their exact status regardless of which slot they land on.

## 6. The archive (answering "archive of what?")

- **New named volume:** `sessions:/data/sessions` (same Docker-volume
  mechanism as `slot-*-profile`; Coolify-managed, survives container
  recreation; node-loss risk class identical to existing volumes —
  backup strategy is a separate item).
- **Contents per user** (`/data/sessions/<user>/`): Chrome profile
  (`/home/neko/.config/google-chrome` **minus cache**) — cookies,
  localStorage, history, extensions (incl. tabbar), session state —
  plus `Downloads` and the tab snapshot. Tens of MB typical.
- **Suspend = copy (rsync, cache excluded) → archive, then wipe the slot
  profile** so the next human never inherits the previous user's identity.
- **Resume = restore archive → slot profile** (onto any free slot).
- Agent sessions suspend/resume identically — the state is the state.

## 7. Implementation pieces

1. **cdp-relay:** timestamp client→browser commands (agent activity
   source). ~30 min.
2. **restart-api:** activity sources (xinput/media/tabs/relay-last-seen),
   reaper thread (check cadence, grace toast, suspend action),
   archive/unarchive helpers (rsync profile↔`/data/sessions/<user>`).
   ~2 h.
3. **router-v2:** `/fleet/release`; on request, if user has an archive →
   wake (restore to free slot) instead of 503; keep single sticky per
   user. ~1.5 h.
4. **compose:** `sessions:/data/sessions` volume + 5 env vars.
5. **tabbar:** grace-countdown toast (reuse toast channel). ~30 min.

**Verification (live, dev fleet):** human session idles → grace toast →
suspend (slot freed, second human gets it) → original human returns →
exact status restored. Same pass with an agent (CDP) session: active
agent never suspended; stuck agent (no commands) is freeable.

## 8. Edge cases

- Stuck/hung agent sends nothing → idle → freeable (desired).
- User returns while all slots busy → 503 with "your session is being
  restored" (restore happens the moment a slot frees).
- Same user, two windows → single sticky/archive (last writer wins on
  suspend; acceptable for internal use).
- Suspend while agent mid-task → activity signal prevents it; a
  long-running task with >15 min silence is treated as stuck (correct).

## 9. W2 DoD mapping

"Idle-stop refinement" → covered by §4–§7 (reaper, variables,
suspend/resume, agent parity). Effort ≈ 4–5 h incl. live verification.

---

## 10. Implementation & verification (2026-08-21, DEPLOYED + E2E-verified)

All five pieces are live on the fleet (`okixw2fxnwn1lakxvxajodww`) and the
viewer (`4guplgcrvug7l7h64m2cxkm1`). Deployed files are the repo files
(md5-verified 2026-08-21):

| File | md5 (repo == deployed) | Notes |
|---|---|---|
| `scripts/restart-api.py` | `d6b7d6a8…` | reaper + activity sources + archive + 2 fixes (§11) + **spec 31 fresh wake** (no-archive user → empty-profile wake, was 500) |
| `scripts/router-v2.py` | `f6545e12…` | `/fleet/release`, archive wake, `/identify` push, 29b sweep + **spec 31 v3** (queue, landing, reaper, agent API) |
| `scripts/cdp-relay.py` | `83812991…` | v3: throttled `/tmp/cdp-activity` touch on C→U chunks |
| `scripts/tabbar-extension/content.js` | `87bedac9…` | v1.8.0 grace-countdown toast |
| `scripts/tabbar-extension/background.js` | `1128d228…` | v1.7.0 (unchanged) |
| `scripts/tabbar-extension/manifest.json` | `826d07d8…` | v1.7.0 (unchanged) |

### Live env (Coolify, current test timings — Tigo asked to shorten)

| Var | Value (fleet slots) | Meaning |
|---|---|---|
| `IDLE_TIMEOUT_MIN` | `2` (default `15`) | idle before grace |
| `IDLE_GRACE_MIN` | `1` (default `5`) | toast countdown |
| `IDLE_CHECK_INTERVAL` | `10` (default `60`) | reaper cadence (s) |
| `IDLE_ACTIVITY_SOURCES` | `xinput,media,tabs,cdp` | all four signals |
| `IDLE_ACTION` | `suspend` | slots suspend; viewer = `none` |
| `PROFILE_DIR` | `/home/neko/.config/google-chrome` | slot profile (reaper default targets viewer's `google-chrome-w1`) |
| `IDENTIFY_SWEEP_INTERVAL` | `30` (router) | 29b identity re-assert (s) |

Compose additions: `sessions:/data/sessions` volume on both slots
(archive store), `sessions: null` top-level declaration.

### E2E verification (slot-2, 1-min timings, 2026-08-21)

`identify → idle → grace → suspend → archive (194M) → wipe → /fleet/release
→ router archive-wake → restore → all 3 tabs back` — full cycle verified
live. Reaper state machine, archive/restore helpers and router branches in
the deployed files; the runbook (§5) carries the manual verification path.

### 29b — slot index persistence + identity sweep (2026-08-21)

- Slot hostname is an opaque container ID, so the router now pushes
  `{"user": email, "slot": k}` on every resolved request (and on a
  30 s sweep, `IDENTIFY_SWEEP_INTERVAL`), so a slot always knows its own
  index and user — even after router/slot restarts with zero traffic
  (the stuck-slot failure mode: reaper logged "no user identified" and
  never suspended).
- Persisted in `$DOWNLOADS/.slot-user.json` (`{"user":…,"slot":…,"ts":…}`;
  downloads volume is slot-bound and never wiped).
- Verified: `.slot-user.json` gained `slot: 2` + fresh ts within 30 s of
  the sweep with zero traffic (router log showed 3 connection-refused
  identifies during its own restart window, then success).

## 11. Post-deploy bug fixes (root causes found DURING the live soak)

### Fix A — reaper blind spot: IPv6-mapped loopback counted as a viewer

**Symptom:** slot-2 burned ~150% CPU with no human watching; `/idle`
reported `status=active, idleFor≈0` every poll while X idle was 2576s+,
no tab changes, no CDP file, EPR UDP unconnected.

**Root cause:** `_media_active()` excluded IPv4 `0100007F` and pure-IPv6
`::1`, but the **title-proxy WS relay to `neko:8080` appears in
`/proc/net/tcp6` as `::ffff:127.0.0.1`**
(`0000000000000000FFFF00000100007F`) — not in the exclusion list → counted
as a remote client session → `media active=True` forever → reaper never
suspends → neko encodes the static screen at ~1 core per open tab.

**Fix (in `restart-api.py`, deployed, md5 `f40bd74e` → superseded by
`749fea5e`):**

```python
rip = remote_ip.lower()
if rip in ("0100007f", "00000000000000000000000001000000") \
        or rip.endswith("ffff00000100007f"):
    continue
return True  # non-loopback client session
```

Verified after deploy: media check with a session OPEN returns False;
`/idle` reported `idleFor=2933s` truthfully → GRACE → SUSPEND fired.

### Fix B — encode survives suspend: title-proxy keeps the neko member session

**Symptom:** after suspend (Chrome stopped), CPU stayed ~90% — the client
tab keeps its WS member session into neko **through title-proxy**
(`127.0.0.1:8DF2 → 127.0.0.1:1F90` ESTABLISHED after suspend) → neko keeps
encoding a static screen at ~1 core until the user closes the tab.

**Fix (restart-api.py, deployed, md5 `749fea5e`):**

1. `do_suspend()`: after Chrome stop → `supervisorctl stop title-proxy`
   (drops the member session).
2. `do_wake()`: after Chrome start → `supervisorctl start title-proxy`.
3. `/identify` handler: if title-proxy is STOPPED, start it (new
   assignments landing on a suspended slot get the UI front back).

Mechanism test (before deploying fix B): `supervisorctl stop title-proxy`
on the live slot → neko CPU dropped to ~0 within seconds; router wake
brought it back.

### Known remaining (W2, not blockers)

- **Healthcheck mandate (Tigo 2026-08-21): "each container of the stack
  should have a healthcheck".** Fleet: router + clamav + janitor have
  checks; **slot-1/slot-2 do NOT** (Chrome/neko container). Viewer stack:
  no healthchecks live (the authored set in the old `fleet-src` compose
  targets the RETIRED `s7fleet` UUID — must be re-applied to the current
  viewer compose). **Pending — needs compose edits + redeploy.**
- Slot 2 CPU abuse during the soak was the stuck CDP harness + reaper
  blind spot (fixed); 1.0 CPU cap (`CPU_LIMIT`) bounds residual damage.
