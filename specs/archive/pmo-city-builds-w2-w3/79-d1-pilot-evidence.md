# D1 — Three-Pilot Live Evidence (2026-08-28/29)

Status: **D1 pilot acceptance evidence recorded; Neko credentials rotated
and live-verified; agent queue timeout implemented and qualified; naming
accepted as the existing per-user email labels.** The remaining W2 closure
condition is the formal SME/DoD sign-off recorded in the D14 evidence.

## Pilot identities (corrected)

The three users are:

- **montigaud@aikumi.pro** — SSO account and Vaultwarden account
- **spike-user@aikumi.pro** — SSO account and Vaultwarden account
- **spike-user2@aikumi.pro** — SSO account and Vaultwarden account

A previously transcribed alias was an error and is not a valid pilot identity;
it must not be used.

## What the current two-pool configuration means

With `N_SLOTS=2`, `CB_HUMAN_SLOTS=1`, and `CB_AGENT_SLOTS=1`, the effective
pool is:

| Slot | Pool | User surface | Current role |
|---|---|---|---|
| slot-1 | human | Neko visual browser | human users |
| slot-2 | agent | bare Chrome/CDP | agent jobs |

`N_SLOTS=2` is the legacy total-slot bound. The active pool calculation is
`1 human slot + 1 agent slot = 2 slots`; the typed pools are disjoint. The
router's code defines slots `1..CB_HUMAN_SLOTS` as human and the following
slots as agent.

### Can a human ever fall on slot-2?

**Not under this configuration through the normal CloudBrowser human path.**
A browser request from an SSO human is assigned only from the human pool
(slot-1). If slot-1 is occupied, that human waits in the human view of the
unified queue; slot-2 is not used as a visual Neko fallback.

A human identity may still be a valid *business user* for an agent job, but
that is a separate agent API entry (`POST /queue`) and is not the human Neko
browser path.

### Can slot-2 only be used by an agent?

**Yes, by design.** With `CB_AGENT_SLOTS=1`, slot-2 is agent-only: bare
Chrome/CDP, no Neko visual-streaming path. The router's `_AGENT_KS` contains
slot-2 and agent assignment loops only over that pool.

### Does slot-2 have an agent queue?

**Yes.** It is not a separate second queue: there is **one unified FIFO queue**
with typed entries (`human` or `agent`). The agent API provides the agent view:

- `POST /queue` with Bearer `CB_AGENT_TOKEN`: immediate assignment if slot-2
  is free; otherwise a typed `agent` entry is queued.
- `GET /queue/<id>`: poll status, position, and ETA.
- `DELETE /queue/<id>`: cancel an agent queue entry.
- `CB_AGENT_QUEUE_TIMEOUT_S=120`: configured hard wait cap for agent queue
  entries.
- Agent jobs consume only agent slots; human jobs consume only human slots.
  FIFO ordering is within the applicable type/pool, with the router selecting
  the eligible type head when a slot becomes free.
- Human users see only the count of waiting agent jobs, not agent identities.

The current live router has `CB_AGENT_TOKEN` set (value intentionally not
recorded), so the agent API is enabled. The live state check after the
correction showed both pools temporarily unoccupied and the queue empty.

## D1 naming decision — ✅ ACCEPTED

Tigo confirmed that the existing labels satisfy the D1 naming requirement:

- `CloudBrowser: <email>`
- `CloudFiles: <email>`

No additional literal `Browser — <name>` label is required for D1.

## What `?pwd=&usr=` means, and whether SSO is enough

### Is it possible to retire `NEKO_PASSWORD`?

**Not while using the stock Neko 2.9.0 client/server unchanged.** This is a
protocol/client constraint, not an authentication-policy decision:

1. The Neko client skips its login form only when the initial URL contains
   `?pwd=<NEKO_PASSWORD>&usr=<display name>`.
2. The Neko WebSocket upgrade separately requires that password as
   `/ws?password=...`.
3. Stock Neko 2.9.0 has no no-auth mode that lets the router omit the password
   while preserving the current automatic connection flow.

### Is SSO nevertheless sufficient as the user-facing gate?

**Yes.** SSO is the user-facing authorization gate. The Neko password is an
internal service credential, injected by the router; the user does not type it
or use it as an alternative login. The URL parameters are stripped by the
Neko client after auto-login, although they can be briefly visible during
entry.

So the correct security interpretation is:

- **Retire user-facing password login:** already done — the Neko login form is
  not shown; SSO controls access.
- **Retire the internal Neko password entirely:** not possible with stock Neko
  2.9.0; requires a custom Neko client/server no-auth change, not justified for
  this iteration.
- **Rotate the internal password:** completed after Tigo updated the Coolify
  ENV table and redeployed. Runtime checks show 64-character non-default
  values in router, slot-1, and slot-2; generated `?pwd=` and WebSocket
  authentication continue to match.

The internal `NEKO_PASSWORD_ADMIN` was rotated at the same time. Rotation
caused a fleet redeploy and brief interruption; it does not change the SSO gate
or per-user isolation.

## Prior qualification invalidated

Any earlier D1 evidence naming a wrong alias or treating a two-user test as the
pilot set is superseded by this correction. The corrected three-user access
classification was live-verified after redeploy:

- `montigaud@aikumi.pro` → `active` on the human path
- `spike-user@aikumi.pro` → `waiting`, position 1, on the human path
- `spike-user2@aikumi.pro` → `active` on the agent path

The agent queue hard timeout is now implemented and qualified:

- commit `2824db1` (`fix(cloudbrowser): enforce agent queue timeouts`)
- local router regression suite: **124/124 green**
- direct timeout regression: a queued agent request returned
  `status: timeout`, `position: null`, and `eta_s: 0` after the configured
  `CB_AGENT_QUEUE_TIMEOUT_S=120` interval
- the timeout is lazy-enforced by queue status reads and reaper processing;
  timed-out entries are removed from the active queue and are not offered a
  slot later

The three-pilot D1 acceptance evidence remains. Tigo's pilot acceptance was
recorded on 2026-08-29:

- `montigaud@aikumi.pro` → active on the human path
- `spike-user@aikumi.pro` → waiting, position 1, on the human path
- `spike-user2@aikumi.pro` → active on the agent path

All three pilot identities are the corrected addresses listed above; no alias
is valid. D1 is therefore **implementation-complete and live-qualified**.
The associated D14 CRM record and Tigo's SME/DoD acceptance are in
`80-d14-crm-evidence.md`.
