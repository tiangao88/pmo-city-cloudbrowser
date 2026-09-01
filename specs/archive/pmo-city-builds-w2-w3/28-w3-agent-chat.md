# W3 Design — Agent in the Neko Chat (28)

> **Status:** design note (logged 2026-08-20). **Decision (Tigo):** Path A —
> WebSocket bridge, agent joins the neko room as a member. **Scope:** W3
> (Aug 31–Sep 6, CRMOC teams). **Not started** — this note is the design
> record only; implementation waits for the W3 go.
>
> **Key scoping decision (Tigo 2026-08-20):** the agent in the chat is the
> **agent of the human of that particular slot** — it is the *per-slot /
> per-owner* agent that already drives that browser. It is **NOT** a
> supervisor/control-plane agent that sees every slot. One agent per browser,
> aligned with `MAX_RUNNING_BROWSERS` and the per-user browser model (FR-1).

---

## 1. Objective

Let the user chat with their own AI agent inside the **existing neko chat
panel** — the same room chat that is already rendered in the viewer UI. The
user types in the panel; the agent (the one driving *their* browser via CDP)
reads it, acts in the live browser, and replies in the same panel.

This makes the chat panel the **input channel** to the agent that already
controls the browser — it does not replace the CDP/browser-use control loop
(the W2 architecture). The chat is a front-end for the same control loop.

## 2. Chosen approach — Path A: WebSocket bridge (agent as a room member)

| Aspect | Detail |
|---|---|
| **What** | The agent (or a thin sidecar it owns) joins the neko room over neko's WebSocket protocol as a synthetic member; subscribes to the room's chat stream (`chat.{room_id}` NATS subject); posts replies back through the same channel as that member. |
| **Why** | Zero fork (no patched neko image), reuses the proven CDP control loop, works identically per-slot and on the viewer, bounded implementation (neko WS member handshake once). |
| **Rejected alternatives** | **B — patch neko's chat handler** (`chat.go` → `Broadcast`) to forward to a webhook: medium–high effort, fork maintenance on every neko upgrade (we pin `google-chrome:2.9.0`). **C — sidecar widget replacing the panel** via title-proxy injection: medium effort, but it stops being "in the neko chat" (our own panel that looks like it). |
| **Constraints** | Neko chat is **plain-text** (neko-markdown is applied client-side for rendering, but the wire format is text) — no rich controls/typing indicators without extra work. The agent posts as a room member, so it must be a *recognizable identity* (display name) so users can tell it apart from humans. |

## 3. Scoping decision — per-slot owner agent (NOT a supervisor)

- The agent that answers in a slot's chat is the **same agent that drives that
  slot's browser** — the human's own agent for that browser (per-user model).
- It has **no visibility** into other slots' chats, tabs, or browsers.
- No control-plane / supervisor agent that aggregates all slots. (That shape
  is explicitly out of scope for this feature.)
- This matches the production model: one immutable browser per employee
  (FR-1), one agent per browser (`MAX_RUNNING_BROWSERS`), per-user isolation
  is structural.

## 4. Open questions for W3 (not blocking the design record)

1. **Identity/auth:** how the synthetic member authenticates to the neko room
   (neko password / admin flag) and how its display name is chosen
   (e.g. "Agent", or the user's own name + "(agent)").
2. **Privilege model:** the agent-as-member can see the room chat; should it
   also be able to *control* via the chat (e.g. "open the CRM", "download
   this") — it already can via CDP regardless, so the chat is about UX, not
   capability.
3. **Chat state & history:** whether the agent should persist per-slot chat
   context across sessions (tie-in with D5 persistence and the agent's
   session store).
4. **Concurrency:** one human + one agent in a room; whether multiple humans
   could ever share a slot (they cannot per current model) — chat arbitration
   is therefore trivial but should be stated.

## 5. Related work / tie-ins

- W2 autonomy docs: `21-w2-autonomy.md`, `24-w2-decision-briefs.md`.
- Agent/browser control: `07-agent-api.md` (MCP parked as future-version;
  browser-use over CDP is the live W2 driver).
- Downloads retrieval was reworded to "agent-in-chat" in W1 (`10-w1-status.md`)
  — this design gives that wording its actual mechanism.
- Branding/toolbar: `title-proxy.py` injection (agent chat panel stays the
  native neko chat; no title-proxy change needed for Path A).
- Capacity: per-slot agent adds CPU/RAM; revisit `16-capacity-measurements.md`
  numbers when implementing.
