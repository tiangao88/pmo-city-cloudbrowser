# Decision Gate — 5 Questions Before Implementation

> Status: **CLOSED — all 5 answered by Tigo (voice notes, 2026-08-15).**
> Answers are folded into the specs. This file keeps the record.

---

## Q1 — Naming & domain ✅ ANSWERED

- **Product name:** **Cloud Browser** (customer-facing name).
- **Domain (dev):** `cloudbrowser.dev01.pmo.city`.
  - Voice note said "pmo.ct" — read as `pmo.city` (same transcription artifact
    as "PMOCT"; existing pattern is `*.pmo.city`). Flag if wrong.
- **Domain (prod):** follows the pattern → `cloudbrowser.pmo.city` (proposal).

**Answer (Tigo):** *"Let's call it Cloud Browser… cloudbrowser.dev01.pmo.city."*

---

## Q2 — Share-vault topology ✅ ANSWERED

- **One central** agent-share Vaultwarden (not per-employee instances).
- **One OIDC setup** for the whole instance.
- **One organization, one collection per employee** — each employee logs in
  (M365 via OIDC) and sees **only their own collection**.
- **Token flow confirmed:** agent asks in chat → employee logs in → Vaultwarden
  issues a token, **stored server-side** in Hermes' secret store, consumable
  **only by the deterministic broker** → broker can see only that employee's
  collection. The chat/agent never sees the token.

**Answer (Tigo):** *"One central Vaultwarden, one OIDC setup, each employee
logs in and we can see this employee's collection… the employee logs in
Vaultwarden, that creates a Vaultwarden token, which is stored, and with that
token the cloud browser login system can only see that employee's collection."*

---

## Q3 — Audience & commercialization ✅ ANSWERED

- **Sellable component:** Cloud Browser ships **inside the comprehensive PMO
  City solution**; the bridge we develop internally is **proprietary /
  commercial license**.
- **Licensing confirmed viable:** MIT dependencies don't force the bridge to
  be MIT (permissive license; keep notices). AGPL Tinyauth stays a separately
  operated service (no infection). FSL stays out.
- **Audience staging:** ① Tigo alone → ② Tigo + a few testers (PMO City
  teams) → ③ client teams, in the context of the **MVP with Groupe Alsei**.

**Answer (Tigo):** *"We're building a proprietary bridge that we include into
our PMO City solution, we will sell it with PMO City… if it is possible, I
would like to keep that commercial license for this particular part."* +
*"First of all me, then me plus a few testers, PMO City teams, and when that
works, client teams in the context of our MVP with Groupe Alsei."*

---

## Q4 — Login autonomy level ✅ ANSWERED

- **Configurable parameter**, per user.
- **Default: (B) confirmation prompt** — users won't trust the system at
  first; agent asks before filling credentials.
- **Switchable to (A) fully autonomous** once the user is comfortable.
- Spec consequence: audit must record which mode was active per login.

**Answer (Tigo):** *"It should be configurable… in the beginning the users
will not trust the system, so they would opt for B confirmation prompts. And
as they become comfortable, they will switch to A. So this should be a
parameter."*

---

## Q5 — Single identity provider ✅ ANSWERED

- **One IdP for everything** — but **not necessarily M365**: any
  **OIDC-compatible provider** (M365/Entra is the concrete first one).
- Vaultwarden supports OIDC; Tinyauth **redirects to the same OIDC provider**
  → one login for viewer + MCP + share-vault.

**Answer (Tigo):** *"We want to go with a single identity provider, not
necessarily M365, it could be any OIDC compatible provider. Vaultwarden is
compatible with OIDC, and Tinyauth is then redirected to an OIDC. So yes, we
want a single identity provider."*

---

**All five answered — gate closed. Implementation can be planned against the
folded specs. Remaining open points (non-blocking, batches C–H) still in
[00-clarifying-questions.md](00-clarifying-questions.md).**
