# Cloud-Browser Service for PMO City — Design Proposal

> Status: **proposal** (not a brick yet). Outcome of the `tools-considered`
> evaluation of open-computer-use (FSL license = commercial blocker) and its
> MIT-licensed equivalents. This design builds the same capability on **MIT
> parts** so it can be **included in PMO City (the product we sell)**.
> See [`open-computer-use/evaluation.md`](../open-computer-use/evaluation.md)
> and [`browser-use/evaluation.md`](../browser-use/evaluation.md).
> **Specs phase open (2026-08-15): detailed PRD is being written as multiple
> files under [`specs/`](specs/README.md) — entry point for requirements,
> starting with [clarifying questions](specs/00-clarifying-questions.md).
> New requirement captured: **Vaultwarden autonomous login** (FR-6 in
> [functional requirements](specs/02-functional-requirements.md)).

## The functional story (what the user experiences)

1. An employee asks their personal agent (Hermes): *"Browse LinkedIn for me and
   summarize my notifications."*
2. Hermes answers with a **link** (in Telegram or any chat channel).
3. The employee clicks the link from **any computer** (office, home, client
   site).
4. They land on the company **SSO** page, authenticate once.
5. The browser that opens is **their personal cloud browser**: all their tabs
   are exactly where they left them, and their existing logins (LinkedIn,
   internal tools…) are already active.
6. They can use it themselves (click, type, log into LinkedIn) **or** hand
   control to Hermes, which navigates, fills, and extracts — while the
   employee watches live.
7. They close the tab on this computer; from another computer tomorrow, the
   same browser, same tabs, same logins are still there.

**The one-sentence product:** *"A persistent, personal, agent-controlled
browser that lives in the cloud and is reachable from any device through a
link."*

## The problem we are solving

- Every employee of PMO City (and of our clients) will run a personal Hermes
  agent that must act **on their behalf inside company IT systems**.
- Acting on behalf requires a **real browser** with **real authentication
  state** (SSO sessions, per-app logins) — and that state must never be
  readable by the agent as raw credentials.
- Existing candidates fail on one of two axes:
  - **open-computer-use** matches the architecture exactly (server-side
    browser, persistent per-chat containers, clickable links, MCP control) but
    its **FSL-1.1 license prohibits selling** it hosted/embedded in a
    competing product.
  - **MIT/Apache tools** (browser-use, playwright-mcp, chrome-devtools-mcp)
    are locally-oriented or lack the cloud-resident viewer + persistence
    packaging.
- **Decision:** build the capability on MIT parts (browser-use + persistent
  Chromium profile + our own viewer/proxy), which we **own and can sell**.

## Design goals

1. **Cloud-resident**: the browser (and its profile) lives server-side; no
   dependency on the user's device.
2. **Persistent & personal**: one browser profile per employee; tabs and auth
   survive across sessions and devices.
3. **Link-first access**: the entry point is a link (SSO-gated) — usable from
   any computer.
4. **Agent-controllable**: Hermes drives the same browser via MCP (navigate,
   click, fill, extract).
5. **Credentials-safe**: user types passwords/2FA directly in the browser; the
   agent only ever sees page state.
6. **License-clean**: MIT/Apache-2.0 only — sellable inside PMO City.
7. **Self-hosted**: runs on our infrastructure (dev01 → prod), no third-party
   cloud dependency.

## High-level topology

```text
┌─────────────┐   link (Telegram/chat)   ┌──────────────────────────────┐
│  Employee   │ ───────────────────────► │  SSO gateway (Tinyauth)      │
└─────────────┘                          └──────────────┬───────────────┘
        │  click link (any device)                      │
        ▼                                               ▼
┌──────────────────────┐   MCP (Streamable HTTP)   ┌──────────────────────┐
│  Browser Viewer UI   │ ◄────────────────────────► │  Hermes agent        │
│  (live CDP stream +  │                            │  (personal, per-user)│
│   input proxy)       │                            └──────────────────────┘
└──────────┬───────────┘
           │ CDP (internal, 127.0.0.1)
           ▼
┌──────────────────────────────────────────────────────────────┐
│  Browser Service (per employee)                               │
│  ┌────────────────────┐  ┌─────────────────────────────────┐  │
│  │ Chromium (headed)  │  │ Persistent profile volume       │  │
│  │  - tabs            │  │  - cookies / logins / sessions  │  │
│  │  - extensions      │  │  - bookmarks / history          │  │
│  └────────────────────┘  └─────────────────────────────────┘  │
│         ▲  Playwright/CDP (browser-use)                        │
│         └──────────── Hermes control plane                     │
└──────────────────────────────────────────────────────────────┘
```

## Identity & access model

- **One browser per employee (DECIDED 2026-08-16, gate Q1)** — a **single
  instance** keyed by their stable, **immutable `user_id`** (same opaque
  identity model as the Composio per-user design — see
  [`composio/design.md`](../v0.1/composio/design.md)). Browser ownership is
  **never** tied to an agent session/conversation ID — every conversation
  resolves to the user's one browser via `user_id` (FR-11). Separation of
  contexts happens through **tabs** inside that browser. Exception:
  **transversal/service agents** (FR-14) own service-account browsers
  (`svc-crm`), never shared with employees.
- **SSO in front**: the viewer link and the MCP endpoint both sit behind the
  SSO gateway — **Tinyauth** (lightweight, OpenID Certified, Docker-native
  forward-auth; see [`../tinyauth/evaluation.md`](../tinyauth/evaluation.md)).
  Tinyauth provides the login page (username/password, LDAP, or OAuth/OIDC to
  a client IdP) and gates every route of the browser service. No raw HTTP
  exposure to the internet.
- **Agent binding**: Hermes authenticates to the browser service with a
  per-user token (issued by the same SSO), so an agent can only drive *its
  owner's* browser — no cross-user access.
- **Secrets**: the browser profile volume is the only place credentials
  live; it is mounted per-user and never shared; the agent has no read access
  to the profile files (only to CDP page state).

## How the agent controls the browser

- **Control plane**: browser-use (MIT) driving Chromium over Playwright/CDP.
  Confirmed capability: attach to a remote browser via `cdp_url` — so the
  agent's browser-use instance can control the *cloud* Chromium, not a local
  one.
- **Profile sync**: browser-use `profile-use` syncs the user's auth profile to
  the remote browser (logins persist); a mounted persistent volume is the
  server-side home of the profile.
- **Viewer**: a small CDP-streaming web app (WebSocket proxy like
  open-computer-use's `browser-viewer.js`, MIT-reimplemented) renders the live
  screen + forwards user input (click/type/scroll). This is the "link" the
  agent sends.
- **Files**: outputs (downloads, scrapes, exports) are served back via HTTP
  links under the same SSO, mirroring the file-flow pattern.

## Execution binding (options, in increasing build effort)

> **Deployment model (DECIDED 2026-08-16, B3): sovereign single-tenant** —
> PMO City is deployed on the client's own server(s): one client, one
> server, one deployment. All capacity/isolation parameters are
> per-deployment. Engine: **Chromium only (C1)**.

1. **Option A — one container per employee** (recommended POC target): a
   service (Docker container per user, or one service with per-user Chromium
   profiles) exposing: viewer route + CDP proxy + MCP endpoint. Profile in a
   named volume. Simple, isolated, matches the per-chat model proven by
   open-computer-use. Capacity-slotted per FR-16.
2. **Option B — shared browser daemon + per-user profiles**: one Chromium
   service process managing N profiles. Cheaper at scale; more shared-state
   risk; revisit after POC.

## Lifecycle

- **Provision**: first link click → SSO auth → browser service creates the
  user's profile volume + starts Chromium → returns viewer link.
- **Persist**: tabs and auth live in the profile volume; container restarts
  re-attach to the same volume (same browser, same state).
- **Idle/GC**: stop Chromium after idle timeout (profile volume retained);
  optional snapshot for backup.
- **Revoke**: SSO deprovisioning stops the browser, unmounts the volume;
  data-retention per client policy.

## Audit & evidence

- Viewer + MCP actions logged per user (who, when, which domain, which tool
  call) in the existing operator audit trail (same pattern as composio audit
  section). No credentials logged — only page URLs and tool names.
- Evidence for the client: per-user browser sessions are attributable and
  reviewable (the employee watches live; audit log shows the agent's actions).

## What this design explicitly does not do

- **Not** a general remote-desktop/VDI product (browser only).
- **Not** credential vaulting: the browser holds credentials; we do not build
  a password manager (that stays with Vaultwarden).
- **Not** multi-tenant browser sharing: strictly one employee = one browser.
- **Not** a multi-tenant platform: sovereign single-tenant per client
  (B3, 2026-08-16); data on the client's EU-located server (D4).
- **Not** an open-computer-use fork/embedding (license-clean by construction).

## Open items (out of this design, tracked elsewhere)

1. **Commercial license from Wide-Moat?** Option to keep open-computer-use as
   an internal-only reference or negotiate a license — parallel track, not
   blocking.
2. ~~**SSO gateway choice**~~ — **DECIDED 2026-08-15: Tinyauth** (see
   [Identity & access model](#identity--access-model) above). Lightweight,
   OpenID Certified, Docker-native forward-auth; AGPL — fine as an operated
   gateway (separate service, like Vaultwarden), **not embedded** in the
   product. Federation to a client's IdP via OIDC if present.
3. **Browser fleet sizing** (RAM per profile; how many concurrent employees)
   — needs a POC measurement.
4. **Viewer implementation** — build a minimal CDP-streaming viewer vs reuse
   an MIT component (e.g. noVNC-style or a thin wrapper); POC decides.
5. **MCP integration surface in Hermes** — per-user MCP registration
   mechanics (same pattern as per-user Composio, see composio/design.md).
6. **File-flow details** — downloads/exports routing and retention.

## Next step (POC on dev01)

1. Deploy a single-employee PoC: Chromium in Docker + persistent profile
   volume + browser-use attached via CDP + minimal viewer + SSO in front.
2. Verify end-to-end: agent sends link → SSO → browser opens with previous
   tabs/logins → agent navigates LinkedIn → user takes over and types 2FA →
   agent resumes → close, reopen from another device, state intact.
3. Measure footprint (RAM/CPU per active browser) → inform fleet sizing.
4. On success: graduate to a brick under `internal/luna/<version>/` per
   `BRICK-TEMPLATE.md` (install.md + SKILL.md + Operator side), and add a
   `VERSIONS.md` row.

## Cross-references

- [`browser-use/evaluation.md`](browser-use/evaluation.md) — MIT engine, remote-CDP capability
- [`open-computer-use/evaluation.md`](open-computer-use/evaluation.md) — reference architecture + FSL blocker
- [`playwright-mcp/evaluation.md`](playwright-mcp/evaluation.md) — local-first alternative
- [`chrome-devtools-mcp/evaluation.md`](chrome-devtools-mcp/evaluation.md) — attach-mode alternative
- [`docs-mcp-server/evaluation.md`](docs-mcp-server/evaluation.md) — client-knowledge companion tool
- [`../v0.1/composio/design.md`](../v0.1/composio/design.md) — per-user identity/execution-binding precedent
- [`../v0.1/CRONS.md`](../v0.1/CRONS.md), [`../v0.1/WORK-QUEUE.md`](../v0.1/WORK-QUEUE.md) — operator indexes
