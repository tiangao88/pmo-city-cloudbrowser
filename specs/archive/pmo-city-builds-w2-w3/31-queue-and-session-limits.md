# Spec 31 — Unified wait queue + session duration limits for the cloud-browser fleet (W2)

**Status:** DRAFT — design locked with Tigo (2026-08-21); no code before approval.
**Scope:** a single unified wait queue (human + agent entries), fixed per-tier slot
pools, max session duration per tier — all driven by **qualified environment
variables** — replacing the current static "All browsers are busy" page with a
real queue experience.
**Depends on:** spec 26 (S7 fleet), spec 29 (idle suspend/resume — eviction is
*suspend*, never logout), spec 30 (Neko resource research — why slots are capped).
**Changes:** router-v2.py (queue engine, busy page → queue page, agent API),
slot lifecycle (max-duration enforcement), env surface (new `CB_*` vars).

---

## 1. Problem

- Browsers are a scarce shared resource: human slots (Neko streaming) and
  agent slots (bare Chrome/CDP) both cost real CPU/RAM (spec 30: a slot ≈
  3–4 GB + cores at Neko "Recommended"; bare Chrome an order less but not free).
- Today the fleet is capped and, when full, serves a static
  **"All browsers are busy"** 503 page (router-v2.py `BUSY_PAGE`) — no feedback,
  no position, no ETA. Waiting humans don't know if it's 30 s or 30 min.
- Agents (programmatic clients) get a bare 503 with no structured wait
  semantics, so they can't decide "wait vs retry-later" intelligently.
- Without a max session duration, a parked human can hold a slot for hours
  (durable sessions make this attractive) → the queue starves.

## 2. Decisions (locked with Tigo, 2026-08-21)

1. **Two tiers, fixed slot counts, env-configured:** human (Neko) slots and
   agent (bare Chrome) slots are separate pools, both bounded by server
   memory/CPU.
2. **Single unified queue**, one FIFO, entries typed `human` | `agent`.
   Human page and agent API are two views of the same queue.
3. **Smart head selection:** FIFO within type; when the next free slot is of
   type X and the queue head is of type Y, the router may skip to the first
   entry of type X (type-aware fairness, starvation guard both ways).
4. **Admin preemption:** admins jump the queue (become next in line; everyone
   shifts down). **Never force-suspend** a running job to make room.
5. **Max session duration per tier:** human short (test default 5 min), agent
   long. Expiry = **suspend + persist** (spec 29 semantics), NOT logout —
   durable profile means the user can re-queue and reclaim their session.
6. **Agent wait semantics:** hard queue timeout env var; on expiry the agent
   call fails fast with a structured error (agent treats it as "try later").
7. **Human queue page shows the email addresses of authenticated humans**
   waiting (transparency; also makes testing with 2 users visible).
8. **All knobs are qualified environment variables** (`CB_*` prefix, see §4).

## 3. Architecture

```
                    ┌──────────────────────────────────────────┐
  human browser  ──▶│  router-v2.py (fleet front door)         │
  (SSO auth)        │  - slot pools: human[] / agent[]         │
                    │  - unified queue: {type,id,prio,enq,st}  │
  agent API  ──────▶│  - head selection (type-aware)           │
  (token auth)      │  - admin priority jump                   │
                    │  - max-duration reaper                   │
                    └──────┬───────────────┬───────────────────┘
                           │               │
                    slot-h-<k> 8081   slot-a-<k> 9230
                    (Neko+Chrome)     (bare Chrome+CDP)
                    durable profile   durable profile
```

- Queue state lives in the existing router state file
  (`ROUTER_STATE`, `/data/state/router-state.json`) → survives restarts.
- Slot assignment reuses the existing sticky / archive-wake paths
  (spec 29); the queue only changes *who* gets offered a freed slot.
- Eviction (max duration or idle) = spec 29 suspend: freeze the slot,
  persist the profile, free the pool slot for the next queue entry.

## 3.1 Profile portability across pools (locked with Tigo, 2026-08-21)

**The user's personal session is a portable archive, not a physical slot.**
A user's Chrome profile lives in the per-user archive
(`/data/sessions/<user>/`, spec 29 §6) and can be **loaded by any slot of
either pool, one at a time** — H when a human must interact, A when the
work is agent-only. The same identity (cookies, localStorage, extensions,
tabs) follows the user regardless of which slot type restores it.

Explicit, driving use case:

1. **Human-assisted login (slot-h).** An agent task needs the user to log
   in to a website. The agent request lands on a **slot-h** (the only pool
   that can present a browser to a human), opens the site, invites the
   user, and the user authenticates. When the session idles out or is
   evicted (spec 29), the profile — cookies included — is archived to
   `/data/sessions/<user>/` and the slot is freed.
2. **Agent-only follow-up (slot-a).** Later (e.g. the next day), the agent
   needs to return to that website. The request lands on a **slot-a**
   (bare Chrome+CDP), the archive is restored onto that slot, and the
   agent finds the user still logged in — no re-authentication, and no
   video pipeline burning CPU for a session nobody is watching.

Rules:

- **One user, one active session.** The archive is a single unit; at most
  one slot (of either type) may hold a given user's profile at a time.
  The existing single-sticky-per-user rule (spec 29 §7) applies across
  pools.
- **Portability is via the archive, not the volume.** Slots still have
  per-slot volumes for the *running* profile; the archive is the
  per-user persistence layer and the only thing that crosses pools.
- **Agent sessions suspend/resume identically** — *the state is the state*
  (spec 29 §6). No pool-specific profile formats.
- **Out of scope for D16:** a human *watching* an agent's live session in
  real time (screen-follow / D13). The pools use different stacks, so
  live watch is not the archive path above; the profile itself remains
  portable in both directions.

## 3.2 Slot sizing — CPU/memory split (locked with Tigo, 2026-08-21)

Per-slot resource caps are **pool-specific** (asymmetric, in the right
direction: humans are interactive, agents are not).

| Pool | CPU limit | mem_limit / shm | Basis |
|---|---|---|---|
| **slot-h** (Neko+Chrome) | **1.0 CPU** | 2 GB / 2 GB | human viewing = encode + Chrome (D17 loaded p95 55.5% was *already above* the old 0.5 cap → throttling → mouse-lag) |
| **slot-a** (bare Chrome+CDP) | **0.5 CPU** | 2 GB / — (no X/video) | agent-only = no encode tax; Chrome mid-task ≈ 0.2–0.4 core; 0.5 leaves headroom |

Implementation notes:

- **`CPU_LIMIT` is per-service in compose** — `slot-h-1` gets `cpus: 1.0`,
  `slot-a-1..3` get `cpus: 0.5` (Coolify: NanoCpus 1000000000 / 500000000).
  The legacy `CPU_LIMIT` env (applied uniformly to all slots today) is
  superseded; per-pool values replace it.
- **Memory stays 2 GB/slot for both pools** (start value). Agent working
  set is ~400–600 MB, so the 2 GB cap is headroom, not tight; revisit
  (1.5 GB) only after agent soak measurements.
- **Whole-fleet envelope on mother01 (8 cores / 32 GB):** 1×1.0 + 3×0.5
  = **2.5 CPU / 8 GB** ≈ 31% of cores — comfortable; leaves headroom for
  authentik/open-webui and future slots.
- **Estimate until measured.** D17 measured the human/encode path only;
  bare-Chrome agent load is unmeasured. Start at these values, run the
  D9 soak against an agent workload, and if agents never exceed
  ~0.3 CPU / 500 MB, drop slot-a to 0.4 CPU / 1.5 GB.

## 4. Qualified environment variables (new `CB_*` surface)

| Variable | Default | Meaning |
|---|---|---|
| `CB_HUMAN_SLOTS` | `1` | fixed size of the human (Neko) slot pool |
| `CB_AGENT_SLOTS` | `3` | fixed size of the agent (bare Chrome) slot pool |
| `CB_HUMAN_MAX_SESSION_MIN` | `5` | max session duration for humans (test value; prod later) |
| `CB_AGENT_MAX_SESSION_MIN` | `240` | max session duration for agents (long) |
| `CB_AGENT_QUEUE_TIMEOUT_S` | `120` | hard wait cap for agent queue entries — on expiry the enqueue call fails fast |
| `CB_QUEUE_POLL_INTERVAL_S` | `5` | human queue page auto-refresh cadence |
| `CB_ADMIN_EMAILS` | `` | comma-separated emails that jump the queue |
| `CB_QUEUE_SHOW_EMAILS` | `true` | render waiting humans' **and active holders'** emails on the queue page (test/ops visibility) |

Notes:
- `N_SLOTS` (legacy) is superseded by `CB_HUMAN_SLOTS` + `CB_AGENT_SLOTS`; keep
  `N_SLOTS` working as a fallback for the human pool during migration, then drop.
- All `CB_*` vars are read once at router start (like today's config) and
  logged at boot for ops.

## 5. Queue model

Entry shape (stored in router state):

```json
{
  "id": "q-8f2a…",            // token; survives page refresh
  "type": "human" | "agent",
  "email": "tigo@…",          // human: SSO email; agent: caller identity
  "priority": 0,              // 0 normal, 1 admin (jump)
  "enqueued_at": "…ISO…",
  "status": "waiting" | "offered" | "active" | "expired" | "left",
  "offer_expires_at": "…"     // grace if a slot is offered but not taken
}
```

Transitions:

```
enqueue ─▶ waiting ─▶ offered (slot freed, head matched)
   │                    │
   ├─ left/expired ◀────┴─ accepted ─▶ active ─▶ (max duration | idle) ─▶ suspended/archived
   └─ agent timeout ─▶ failed-fast (503 + retry-after)
```

## 6. Assignment logic (router)

1. On any request needing a slot:
   - sticky user with an active slot → direct to it (unchanged, spec 29).
   - archive wake → as today, but only if a slot is free.
   - else → enqueue (human: served the queue page; agent: gets queue id).
2. When a slot frees (user leaves, idle-suspend, or max-duration):
   - find first queue entry that can use this slot type (type-aware head
     selection, §2.3; admin priority = compare priority before type).
   - offer → `POST /wake` (existing path) → entry becomes `active`.
   - no match → slot stays free.
3. Admin (in `CB_ADMIN_EMAILS`): enqueued with `priority: 1` → placed ahead
   of all priority-0 entries of the matching type, at the type head.
   Running jobs are never preempted.
4. Max-duration reaper: every `IDLE_CHECK_INTERVAL`, any `active` entry older
   than its tier max → suspend (spec 29), free the slot, notify UI.

## 7. Human UX (queue page)

- Duplicates the neko **top bar** (same 40px `#202225` bar, logo +
  **CloudBrowser** brand — bold C and B) **without the burger** — chat/
  settings do not exist on the queue page. Right side = the PMO City
  shortcuts the session header carries (🔒 Secrets + 📁 CloudFiles pills,
  same as title-proxy) plus the **logged-in user's email** top-right; the
  admin lock toggles are omitted (no session). The center box never shows
  the user's own email — `/queue/status` filters it out of
  `active_humans`/`waiting_humans` server-side.
- Replaces `BUSY_PAGE` when the queue is non-empty (or always when full).
- Shows: **your position**, estimated wait (queue-ahead × median session
  remaining, best-effort), and — with `CB_QUEUE_SHOW_EMAILS=true` — the
  **email addresses of waiting humans** (and a count of waiting agents).
- Auto-refreshes every `CB_QUEUE_POLL_INTERVAL_S` (or SSE push, later).
- On `offered`: auto-redirect into the session (wake already restores the
  durable profile).
- Token (`q-…`) in a cookie/URL so refresh doesn't lose the place.

## 8. Agent API

- `POST /queue` (token auth) → `202 {queue_id, position, eta_s}` or
  `503 {queue_id, position, retry_after_s}` when queued; on
  `CB_AGENT_QUEUE_TIMEOUT_S` elapsed → `503 {error: "queue_timeout"}`.
- `GET /queue/<id>` → current position / status (polling contract).
- `DELETE /queue/<id>` → leave the queue (agent cancelled).
- Agents may also observe who is in the fleet (human/agent occupancy) via
  the existing `/fleet/status` — extended with queue depth by type.

## 9. Max session duration semantics

- Human: `CB_HUMAN_MAX_SESSION_MIN` (5 in test) → a toast warning at
  `IDLE_GRACE_MIN`-style horizon ("Session ends in 5 min — queue again to
  reclaim"), then suspend+persist. **Not a logout** — cookies/logins live in
  the durable profile.
- Agent: `CB_AGENT_MAX_SESSION_MIN` (240) → hard cap; long-running agent jobs
  must renew (heartbeat API, later) or be suspended.
- Suspended entries go to `archives` exactly like spec 29 idle-suspend.

## 10. Testing plan (Tigo-approved scenario)

| Setting | Value |
|---|---|
| `CB_HUMAN_SLOTS` | `1` |
| `CB_AGENT_SLOTS` | `0` (or 1) — test human path first |
| `CB_HUMAN_MAX_SESSION_MIN` | `5` |
| `CB_QUEUE_SHOW_EMAILS` | `true` |

1. Two test users (A, B) authenticate → A gets the slot, B sees the queue
   page with A's… wait: A is *active*, B sees the queue **including B's own
   email** and position 1.
2. A's session hits 5 min → toast → suspend → B is offered → B lands in
   A's exact session (profile restored).
3. Admin C enqueues during B's session → C appears at the head (position 0)
   but B is not kicked.
4. Agent enqueue with `CB_AGENT_QUEUE_TIMEOUT_S=120` behind a long human
   session → fails fast with `queue_timeout`, retries later.

## 11. Non-goals (this iteration)

- No preemption/kick of running sessions (admin or otherwise).
- No multi-queue UI (one queue, two views).
- No SSE push (polling suffices for v1; SSE is a drop-in later).
- No agent heartbeat/renewal API (post-MVP, §9).

## 12. Open questions — RESOLVED (Tigo 2026-08-21)

**Q1 — ETA quality: adaptive rolling median + fallback (agreed).**
- Router records actual session durations per tier (last ~50 completed) and
  computes `ETA = (queue-ahead ÷ free-coming-slots) × median observed
  duration`, floored at one poll interval.
- Cold start (no data yet): fallback `tier max ÷ 2` until real numbers arrive.
- Self-corrects after the first few sessions; ~10 lines on top of existing
  router state. (Rejected alternative: static `position × CB_HUMAN_MAX_SESSION_MIN` —
  systematically wrong both directions.)

**Q2 — Agent visibility to humans: count only (agreed).**
- Human queue page shows "*…plus N agent jobs waiting*" as a bare count.
- Agent identities (service emails, job ids) stay internal — GDPR-friendly,
  no info leak. (Rejected alternatives: hide entirely — humans at "position 1"
  for 10 min would be confused; full agent identities visible — no upside,
  real leak risk.)

## 13. Implementation plan (executed 2026-08-21)

> Plan documented per Tigo's standing rule (implementation plan before code).
> Phases below were followed in order; status reflects live verification.
> Evidence for every step: `36-spec31-results.md`.

### Phase 1 — Router v3 (`scripts/router-v2.py`, ~710 lines)

| # | Step | Deliverable | Status |
|---|---|---|---|
| 1.1 | Queue engine | Single FIFO `deque`, type-aware head selection (agent jobs only consume agent slots), admin jump-ahead (`CB_ADMIN_EMAILS`), entry `{id, type, email, priority, enqueued_at, status, slot, offer_expires_at}` | ✅ |
| 1.2 | Landing page | SSO-gated; free slot → "Open Browser" button with `/?pwd=…&usr=…` (neko 2.9.0 auto-login: `connect.vue` URL params + WS `?password=`; params stripped via `pushState` — neko login form never shown); busy → 303 `/queue/<id>` | ✅ |
| 1.3 | Queue page | Position, adaptive ETA (rolling median of last 50 completed durations/tier; cold start `tier max ÷ 2`; floor = poll interval), waiting humans list + agent count, auto-refresh | ✅ |
| 1.4 | Max-duration reaper | Router owns session clock; expiry → `POST /suspend` (idempotent) → archive `reason=expired` → next offer; idle-suspend (spec 29) still archive-wakes (walk-away ≠ expiry) | ✅ |
| 1.5 | Agent API | `POST/GET/DELETE /queue`, Bearer `CB_AGENT_TOKEN`; 202 + instant-grant fast path on free agent slot; 501 when token unset | ✅ |
| 1.6 | Boot hygiene + locking | Purge stale stickiness outside pools; `_queue_lock` → `_lock` order (deadlock fix); serialized state saves; sweep 30 s, reaper 10 s | ✅ |
| 1.7 | Local harness | `scripts/test-router31.py` (+ `router31-bootstrap.py` getaddrinfo monkeypatch → 127.0.0.1); fake slots on 19081/9230; **14/14 pass** (incl. regression: release drops queue entry) | ✅ |

### Phase 2 — Compose (`cb-fleet-v2`, uuid `okixw2fxnwn1lakxvxajodww`)

| # | Step | Deliverable | Status |
|---|---|---|---|
| 2.1 | Router env block | `CB_HUMAN_SLOTS=1`, `CB_AGENT_SLOTS=0` (human path first), `CB_HUMAN_MAX_SESSION_MIN=5`, `CB_AGENT_MAX_SESSION_MIN=240`, `CB_AGENT_QUEUE_TIMEOUT_S=120`, `CB_QUEUE_POLL_INTERVAL_S=5`, `CB_ADMIN_EMAILS=` (empty), `CB_QUEUE_SHOW_EMAILS=true`, `CB_AGENT_TOKEN=` (empty), `NEKO_PASSWORD=${NEKO_PASSWORD:-neko}` | ✅ |
| 2.2 | Slots | Untouched (no env change) | ✅ |

### Phase 3 — Local verification
Run harness 13/13 green on fake slots (`test-router31.py`).

### Phase 4 — Deploy (Coolify, cloudbrowser dev service — pre-authorized)

| # | Step | Status |
|---|---|---|
| 4.1 | PATCH `docker_compose_raw` (base64-only) via `coolify-local.sh` | ✅ |
| 4.2 | Seed `router-v2.py` into shared `scripts` volume (root:root 644) | ✅ |
| 4.3 | sha256-verify volume file == repo file | ✅ (`7a3c2238…`) |
| 4.4 | Restart service; all 5 containers healthy | ✅ |

### Phase 5 — Live acceptance (§10 scenario)
A lands → slot + Open Browser (no neko login); B lands → queue page + ETA; A expiry → reaper suspends/archives `reason=expired`; A's next landing → **queue page**; B offered slot. Evidence → `36-spec31-results.md`. (A-slot / B-queue live ✅; expiry leg live ✅; agent path deferred — `CB_AGENT_SLOTS=0` this iteration.)

### Phase 6 — Docs & ship
Runbook md5 refresh (`26-s7-fleet-reproduction.md`), results doc (`36-spec31-results.md`), W2 progress log entry, commit + push.

### Non-goals this iteration (unchanged from §11)
No agent heartbeat/renewal API, no persistent cross-boot queue replay, no multi-pool fairness beyond admin jump-ahead, no live agent-slot test (`CB_AGENT_SLOTS=0`).
