> **Refactor update — 2026-09-01:** The original FR-9 principle remains the target,
> but the deployed `sso-broker.py` is only an Authentik/TinyAuth adapter. The
> generic broker contract, profile binding, restricted CDP boundary, adapter
> model, and security acceptance criteria are now proposed in
> `85-credential-broker-prd.md`, `86-product-boundaries.md`, and
> `87-broker-security-model.md`. Until those documents are agreed and the
> boundary tests pass, FR-9/FR-10 below are a product intent, not a claim that
> the current implementation is generic or broker-only enforced.

# Functional Requirements — Cloud-Browser Service (draft)

> Status: **draft**. FR-6/FR-9/FR-10/FR-11/FR-12/FR-13 decided 2026-08-15;
> FR-2/FR-5/FR-6/FR-10/FR-11 revised + **FR-14 (transversal agents), FR-15
> (viewer), FR-16 (fleet capacity) added 2026-08-16 (gate Q2 closed)**.
> Batch 2 (2026-08-16): FR-4 full-control MCP surface + Chromium-only
> engine; FR-12 downloads decided (I1/I2/I5); FR-16 per-deployment scope +
> FR-13 per-deployment gateway (B3); EU residency (D4).
> **Batch 4 (2026-08-16, final):** FR-2 extensions (C2), FR-4 binding scope
> (D2), FR-6 login-failure handling (F7), FR-9 fill mechanism (F4) + broker
> identity (G1) + broker↔vault auth (G6) + zero exposure (F6), FR-10 token
> custody (G1), FR-12 virus scan (I6), FR-13 LLM scope (J1) + env config
> (J3). **All clarifying questions A–J closed.**

## FR-1 Link-first access

- The employee receives a **link** (Telegram or any chat channel) from their
  agent when the agent has something to show / needs them.
- Clicking the link from **any computer** opens the employee's personal cloud
  browser after authentication.
- **URL shape (DECIDED 2026-08-16, A3; SUPERSEDED 2026-08-21 — router + SSO):**
  host-level link `https://cloudbrowser.pmo.city` (dev01:
  `https://cloudbrowser.dev01.pmo.city`) — the **same URL for every
  employee**. Identity comes from the SSO session (tinyauth `remote-user`);
  the router maps it to the employee's own session server-side. The earlier
  per-user subpath `…/u/<short-id>` (short ID to disambiguate same-name
  employees) is obsolete: the router already keys on the authenticated user
  ID, so a URL segment adds nothing — and a shared host-level URL is the
  point (one link works for everyone, no per-user pointers to share).
- The link is SSO-gated (Tinyauth) — no raw HTTP exposure to the internet.

## FR-2 Persistent, personal browser

- Browser instances are **owned by the employee's immutable `user_id`** —
  never by an agent session/conversation ID (explicit requirement, 2026-08-15).
- **ONE browser per employee (DECIDED 2026-08-16, gate Q1):** a single
  instance per `user_id` — whatever session or conversation asks to view the
  browser, it is the same browser. No per-session instances, no multiple
  profiles. The browser has a stable identity and persistent profile.
- **Tabs carry separation**: the one browser has **many tabs** — that is how
  the employee separates contexts (work / client A / personal), all inside
  their single browser.
- **Naming**: **auto-generated, containing the username** — e.g. *"Browser —
  Stéphan"* — so it is unmistakably his: it holds his credentials, everything
  inside is his (gate Q1). Transversal/service browsers: *"Browser — CRM
  (service)"* (FR-14).
- Tabs, cookies, logins, extensions, bookmarks and history **survive across
  sessions and devices** (server-side profile volume).
- **Extensions (DECIDED 2026-08-16, C2): none preinstalled by default** —
  clean profile, minimal attack surface. Per-user extension installs possible
  later (out of year-1 scope).
- Closing the tab on one computer does not lose state; reopening from another
  device shows the same browser.
- **Never expires (DECIDED 2026-08-16, gate Q2):** no inactivity TTL, no
  auto-logout. Logout is **user-triggered only** — "log me out, destroy my
  browser" wipes the profile (cookies, cache, stored credentials);
  **downloads survive** in the durable per-user file area (FR-12).

## FR-3 SSO via Tinyauth (DECIDED)

- Tinyauth is the SSO gateway in front of the viewer link **and** the MCP
  endpoint (decision 2026-08-15, see `../tinyauth/evaluation.md`).
- Supports username/password, LDAP, or OIDC federation to a client IdP.
- **Single IdP (DECIDED 2026-08-15):** Tinyauth redirects to the **same OIDC
  provider** as Vaultwarden (gate Q5) → one login for viewer + MCP +
  share-vault.
- Operated as a separate service (AGPL); not embedded in the product.

## FR-4 Agent control

- Hermes drives the browser via **MCP**.
- **MCP surface — full control (DECIDED 2026-08-16, D1):** navigate /
  back / forward, click, type, scroll, extract, screenshot, **tabs,
  downloads** — everything a person can do (exact tool list:
  [07-agent-api.md](07-agent-api.md)). Read-only mode: deferred, addable
  later.
- **Engine — Chromium only (DECIDED 2026-08-16, C1):** the most standard
  choice; browser-use/CDP integration is Chromium-family by design. Firefox
  out of scope for year 1.
- The agent can only drive **its owner's** browser (per-user token via
  Tinyauth); no cross-user access. **Binding scope (DECIDED 2026-08-16,
  D2): per-user only** — no team/shared browsers in year 1 (service accounts
  are their own owner class, FR-14).
- **Control path (research note 2026-08-15):** Hermes' default browser mode
  is now the **Browser Use CLI 3.0 harness** (`browser_exec`). The agent
  writes **one Python script per step-batch** against a single CDP websocket
  (navigate + click + type + scrape in one call), reads page state
  **text-first** (`page_info()` / `js()` — no raw HTML dumps, no
  screenshot-by-default), and the browser session + workspace persist across
  calls. Result: browser control is far less token-intensive than the old
  per-step DOM-snapshot loop. Harness `session=` isolation composes with
  per-browser isolation. Aligns with the POC plan (browser-use via CDP) —
  see the research summary in `../browser-use/evaluation.md`.
- **Component & license (confirmed 2026-08-15):** Browser Use is a
  **third-party component** (browser-use/browser-use **MIT** +
  browser-use/browser-harness **MIT**), integrated by Hermes as its default
  browser mode. Both are **embeddable in the proprietary Cloud Browser
  bridge** (MIT permits bundling; keep license notices in NOTICE/
  THIRD_PARTY). The harness attaches to any Chromium-family browser over one
  CDP websocket — exactly our architecture (Chromium + persistent profile
  volume + CDP) — so the efficiency gains (one script per step-batch,
  text-first page state, persistent session/workspace) transfer 1:1.

## FR-5 Manual login / 2FA handoff (baseline, REVISED 2026-08-16)

- The employee can use the browser themselves: click, type, log in, including
  2FA where they type the code directly.
- **2FA hybrid (DECIDED 2026-08-16, gate Q3):** for autonomous logins, the
  agent/broker uses **TOTP if present** in the share-vault item (fully
  autonomous); otherwise the agent **asks in chat** and the employee reads the
  code from their authenticator. Never a hard block; never autonomous 2FA
  without the stored secret.

## FR-6 Vaultwarden autonomous login (NEW, DESIGN 2026-08-15)

- Employees store their website credentials in **Vaultwarden**.
- **Dedicated share-vault (Tigo, 2026-08-15):** this Vaultwarden is **NOT the
  employee's daily Vaultwarden**. It is a dedicated vault where the employee
  puts **only the passwords they want to share with the agent**. Nothing else
  lives there → a user-level token reading "everything in that vault" reads
  only what was meant to be shared (structural guarantee, resolves G2).
- **Grant model (DECIDED 2026-08-15):**
  - **(a)** employee shares **specific items** with the agent (item-level share), **and**
  - **(b)** a **dedicated collection** per employee.
  - (c) master password is **rejected** — see FR-9.
- The agent **logs in autonomously** to websites declared in Vaultwarden
  (site URL in the vault item = allowlist, per F8).
- **Autonomy level (DECIDED 2026-08-15, gate Q4): configurable per-user
  parameter** — default **(B) confirmation prompt** before the agent fills
  credentials; switchable to **(A) fully autonomous** once the user is
  comfortable. Audit records which mode was active per login.
- **Login failure (DECIDED 2026-08-16, F7):** on a rotated/stale password,
  the agent reports back to the employee — "login failed for *site* — update
  the vault entry" — and the task **pauses**. No silent retry loops (could
  lock accounts); the agent never updates the vault itself (FR-6 scope).
- **2FA hybrid (DECIDED 2026-08-16, gate Q3):** TOTP if present in the
  share-vault item → broker enters it (autonomous); otherwise the agent asks
  the employee in chat for the code (FR-5).

## FR-9 Deterministic credential broker (NEW — the solution to "agent never sees the password")

> **Principle (Tigo, 2026-08-15):** deterministic parts in software. The agent
> **never has access to passwords**. It only issues an intent — *"log in user
> A to site B"* — and a **deterministic (non-LLM) broker component** performs
> the login using credentials it fetches from Vaultwarden.

- **Who/what the broker is (clarified 2026-08-16, G1):** a **deterministic
  software component** — a small service, **no LLM in the loop**, no human
  role (not a super-admin person). It is the "vault clerk": holds the
  credential-fetch grant, fetches server-to-server, fills forms via CDP,
  makes **no decisions** — executes logins deterministically. Deployed and
  administered by **ops** (PMO City at install), but operationally opaque to
  humans: credentials never pass through a person or the agent.
- **Agent interface:** the agent calls a narrow, intent-only MCP tool
  (e.g. `credential.login(site, username)`). It returns **success/failure
  only** — never the password, never a token that can be replayed to read it.
- **Broker behavior (deterministic software, no LLM in the loop):**
  - resolves the target site + user against the employee's Vaultwarden grants
    (item-level shares + dedicated collection — FR-6);
  - fetches credentials directly from Vaultwarden (server-to-server);
  - fills the login form in the browser via CDP **directly** (no pass-through
    through the agent's context);
  - verifies login success and reports the outcome.
- **Fill mechanism (DECIDED 2026-08-16, F4): CDP injection** — the broker
  pushes credentials via the browser's native DevTools protocol. No browser
  extension to build/sign/maintain; works with any Chromium; consistent with
  C2 (no preinstalled extensions).
- **Broker ↔ Vaultwarden auth (DECIDED 2026-08-16, G6): OIDC session
  token** — the broker authenticates via the single IdP (same OIDC as
  FR-10); preference over static API keys. No second credential store.
- **Guarantees:**
  - plaintext credentials **never enter the LLM context**;
  - credentials **never written to logs, audit trails, or disk** by the agent
    or broker (only the browser profile volume holds them, as today);
  - the broker is the **only** component holding a credential-fetch grant
    (token custody — DECIDED 2026-08-16, G1: **broker only**; the agent holds
    no credential-bearing secret).
- **Open design points** (tracked, not blocking): broker as separate service
  (like Tinyauth) vs embedded in the browser service; audit events emitted by
  the broker (login attempts, outcomes — no secrets; see D3, FR-7).

## FR-10 OIDC into Vaultwarden (single IdP — any OIDC-compatible provider) + delegated token flow (NEW)

> **Tigo's proposal (2026-08-15):** Vaultwarden supports OIDC, so the employee
> logs into Vaultwarden with their **identity-provider account** (OAuth/OIDC).
> The resulting token is stored with the Hermes agent; a deterministic piece of
> software uses that token to log the user into a particular website; the
> agent then has access to the cloud browser session and does the thing.
> **Feasibility: YES** — Vaultwarden supports OIDC login providers, and
> Bitwarden's official docs cover the Microsoft Entra ID (M365) OIDC
> configuration.

- **Single IdP (DECIDED 2026-08-15, gate Q5):** one identity provider for
  everything — **any OIDC-compatible provider** (not necessarily M365;
  Microsoft Entra ID is the concrete first deployment). Vaultwarden uses
  OIDC, and Tinyauth **redirects to the same OIDC provider** → one login for
  viewer + MCP + share-vault.
- **Login**: employee authenticates to Vaultwarden with their **identity
  provider account** via OIDC (no separate Vaultwarden password needed). The
  IdP token is used *only* at login; Vaultwarden then issues its own
  **session/API token** for that employee — this is the token the flow
  actually consumes.
- **Token custody (DECIDED 2026-08-16, G1 — broker only)**: the token is
  stored in the Hermes secret store but is **consumable only by the
  deterministic broker (FR-9) — it never enters the LLM context**. (Same
  pattern as the existing `bw-session.sh` bootstrap: token lives in the
  child process env, never printed or surfaced to the model.)
- **Order → fill**: agent issues the intent-only order (`credential.login(
  site, username)`); the broker uses the stored token against the Vaultwarden
  API to fetch the credential for the requested site (respecting the
  employee's item-level shares + dedicated collection, FR-6) and fills the
  form via CDP.
- **Then the agent acts**: once logged in, the agent drives the cloud browser
  session (FR-4) — it sees page state only, never plaintext.
- **Feasibility notes / caveats to verify in POC:**
  - OIDC + Entra ID is a documented Vaultwarden/Bitwarden configuration;
  - **token scope — RESOLVED by design (2026-08-15):** the agent-facing
    Vaultwarden is a **dedicated share-vault** containing only the passwords
    the employee wants to share. A user-level token can therefore read
    "everything" in that vault and that is exactly the intended exposure —
    no per-item scoping needed (G2 closed);
  - token **expiry/refresh — DECIDED 2026-08-16 (gate Q2):** the browser and
    session **never expire**. If the OIDC/token itself expires, the agent
    **asks the employee to re-login** in chat (link, one tap) and the task
    pauses — no silent refresh of personal credentials. Exception:
    transversal/service agents (FR-14) auto-refresh service-level tokens and
    alert **ops** on failure;
  - **revocation**: employee removes a share → broker loses access to that
    item immediately (verify behavior in POC).

## FR-7 Credential hygiene (REVISED 2026-08-15 — zero-exposure model)

- Supersedes the earlier "transient exposure" framing (agent may momentarily
  read a password): with FR-9, exposure is **eliminated by construction** —
  the agent never receives the plaintext.
- Rules:
  - credentials are never persisted, logged, or written to disk by the agent;
  - credentials are never included in audit logs;
  - only the deterministic broker touches plaintext, only to fill the form.
- The browser profile volume remains the only place credentials persist
  server-side (per-user, never shared).
- **Audit events (DECIDED 2026-08-16, D3 — lean):** logged events =
  login/logout, browser attach, browser destroy, downloads, broker login
  attempts + outcomes. **90-day retention.** Never page contents, never
  credentials (this section). Full navigation/click history logging: not in
  year 1 (revisit only if ops asks).

## FR-11 Browser resolution & attach (REVISED 2026-08-16 — single browser per user)

> **Requirement (Tigo, 2026-08-15):** the employee can list every browser
> where they are logged in and attach to a particular one from within a
> conversation. **Gate Q1 (2026-08-16) simplifies this to a single browser
> per user** — see FR-2. The tools stay, but their semantics collapse to
> "the user's browser".

- **Ownership key**: browsers are registered against the **immutable
  `user_id`** (Tinyauth identity), never the agent session ID. A conversation
  with the agent therefore resolves to the user's browser, not to a
  chat-scoped instance.
- **MCP tool `browser.list()`**: returns the **user's single browser**
  (id, label — auto-generated with username, last-active, status
  running/sleeping), confirming *"every browser where I'm logged in"* = the
  one browser.
- **MCP tool `browser.attach(browser_id)`**: binds the current agent
  interaction to the user's browser. With one browser per user this is
  mostly a **formality** — it exists for API stability and for future
  multiplicity (per-client deployments may re-open several browsers per user
  under B3).
- **Default resolution**: any conversation resolves to the user's single
  browser; no picker needed.
- **Cross-user isolation unchanged**: browsers are never shared across
  employees; the user only ever sees/attaches their own (FR-8).

## FR-12 Durable per-user download storage (NEW — from Tigo)

> **Requirement (Tigo, 2026-08-15):** files saved/downloaded from the various
> cloud-browser instances stay in a **durable file system linked to the
> employee's `user_id`**. The employee can find back **every file they have
> downloaded, from whatever instance** of a cloud browser.

- **Per-user file area**: downloads land in a durable per-user storage
  volume, keyed by the same **immutable `user_id`** as browser ownership
  (FR-2/FR-11) — never tied to a browser instance, a session, or a
  conversation.
- **Find-back guarantee**: the employee can retrieve/list any file downloaded
  — one persistent place, surviving browser restarts, reprovisioning, and
  future multiplicity.
- **Same volume across instances**: whether the download happened in browser
  #1 or browser #2, it lands in the user's shared download area (open points:
  folder layout, access surface, quota — see batch I).
- **Access**: employee-facing retrieval per I1 — **both surfaces (DECIDED
  2026-08-16):** file browser **in the viewer** **and** via the **agent in
  chat** ("list my downloads", "send me file X"). **Agent access: YES
  (ANSWERED 2026-08-15, gate batch I4)** — the file system is accessible to
  the user's Hermes agent, so the agent can **work on the downloaded files**
  (read, process, summarize, re-send).
- **Storage shape (DECIDED 2026-08-16, I2): flat shared area** — one
  per-user download folder across all tabs; same-name re-downloads get
  suffixed (file.pdf → file (1).pdf). Per-instance folders obsolete (one
  browser per user, gate Q1); per-tab/task folders possible later.
- **Routing (DECIDED 2026-08-16, I5): always** — the browser's download
  directory **is** the per-user durable volume; automatic, no per-download
  decision.
- **Quota & retention (DECIDED 2026-08-16, I3):** **5 GB per user**;
  **90-day retention** with auto-purge of files older than 90 days;
  **GDPR erasure** of all files on user delete.
- **Virus scanning (DECIDED 2026-08-16, I6): YES — scan at ingest**; flagged
  files quarantined (not deleted automatically); user notified. Scan engine
  per deployment (ClamAV default — free, self-hosted, EU-friendly).
- **Security model consistent with FR-7**: the file area is per-user, never
  shared across employees (FR-8); contents may hold client data → **EU
  residency on our infrastructure (DECIDED 2026-08-16, D4)** — we guarantee
  our servers/volumes are EU-located; we do not police which external
  websites/services the client's users visit.

## FR-13 Configurable LLM connectivity (NEW — from Tigo)

> **Requirement (Tigo, 2026-08-15):** the cloud browser runs in a **separate
> container** and may require LLM access. Everything must be **configurable**
> — we point it at the **OmniRoute AI proxy** so the LLM configuration is
> deployment-configurable.

- **No hardcoded LLM providers**: any LLM call originating inside the
  browser-service container (browser-use agent mode, autonomous loops, future
  features) is configured via environment/config — never baked into the image.
- **Configurable surface**: base URL/endpoint, model name, API key, timeout —
  per deployment, via env-file or config (pattern `${VAR:-default}`; secrets
  via env-file refs, never plaintext in images or logs).
- **Default = OmniRoute AI proxy**: the PMO City deployment points the
  container's LLM access at the OmniRoute proxy (the same gateway the Hermes
  instances use). Client deployments point at **their own LLM gateway**
  (per-deployment, confirmed by B3 single-tenant — no shared multi-tenant
  proxy routing).
- **Scope note (DECIDED 2026-08-16, J1 — browser-use agent mode only)**: the
  browser-use **harness** itself needs no LLM (the agent writes the scripts);
  LLM access is required by browser-use **agent mode** and any in-service
  agent loop. FR-13 covers all such paths. No other in-container path needs
  LLM in year 1.
- **Config mechanism (DECIDED 2026-08-16, J3): env-file refs** with
  `${VAR:-default}` pattern — no baked config values; secrets via env-file
  refs, never in the image, never logged (FR-7).
- **Secrets hygiene per FR-7**: API keys only via env-file refs / secret
  store; never in the image, never logged.

## FR-14 Transversal / service-agent browsers (NEW — from Tigo, gate Q2)

> **Requirement (Tigo, 2026-08-16):** agents not associated with a user —
> e.g. a company CRM agent — need **access all the time**. That must **never
> expire**, otherwise their workflows cannot proceed.

- **Service-owned browsers**: a browser class owned by a **service account**
  (e.g. `svc-crm`), not by an employee. Same runtime as user browsers, same
  persistent profile volume, same central share-vault access via the
  **service account's own collection** (validated in gate Q2 — the three
  tiny validations).
- **Always on**: never expire, never pause, no user to prompt. Service-level
  tokens **auto-refresh** (unlike user tokens, FR-10); if refresh fails the
  service **alerts ops**, not a chat.
- **Naming**: auto-generated with the service name — *"Browser — CRM
  (service)"* (gate Q2 validation ③).
- **Isolation unchanged**: employees never see service browsers and vice
  versa; cross-user isolation (FR-8) extends to service accounts.
- **Capacity guarantee (ties to FR-16)**: transversal agents get **reserved
  slots** so they are never blocked by human fleet saturation.
- **Agent binding**: the service account's agent (not a person's Hermes)
  drives these browsers; per-service token via the same SSO.

## FR-15 Viewer — link-click, reused MIT component (NEW — gate Q4)

> **Requirement (Tigo, 2026-08-16):** the agent gives a **link in chat**; the
> human clicks it; it opens in **their own device browser**; the page that
> loads **is the browser** (the viewer). **We do not develop that part** —
> reuse an MIT viewer component if one exists. Mic/camera/audio desirable
> from the start, best-effort, not a deal breaker.

- **Link-first viewer flow**: agent sends link → employee clicks (any
  device) → SSO (Tinyauth, FR-3) → viewer page renders the employee's cloud
  browser live (FR-1).
- **Component over build**: the viewer is a **reused component**, not
  self-developed. License bar: MIT preferred; permissive-compatible
  (Apache-2.0/MPL) accepted if MIT is not available — sellable inside the
  proprietary bridge (B2).
- **Media (best-effort, year-1)**: audio (hear pages/meet calls) desirable
  from the start; mic/camera best-effort only if the chosen component
  provides it. Not a deal breaker — page-only viewer is acceptable.
- **Component evaluation & POC spike**: see
  [09-viewer-evaluation.md](09-viewer-evaluation.md) (noVNC MPL-2.0
  page-only candidate; neko Apache-2.0 WebRTC+audio candidate; KasmVNC
  GPL-2.0 excluded). POC decides.

## FR-16 Fleet capacity management (NEW — from Tigo, gate Q5)

> **Requirement (Tigo, 2026-08-16):** protect the server — limit what the
> browser containers can consume (RAM). Finite "on" slots; as many "off"
> browsers as wanted; reserved capacity for service accounts.
> **Scope: per-deployment (B3, 2026-08-16)** — PMO City is sovereign
> single-tenant, so the capacity parameters are sized per client server,
> not globally.

- **Concurrency cap**: `MAX_RUNNING_BROWSERS` (configurable parameter,
  example **5**) — hard limit on simultaneously **running** browsers.
- **Per-container limits**: each running browser container is **RAM-limited**
  (≈1–2 GB) so one browser can never starve the server.
- **Parked browsers**: any number of browsers may **exist but be off** —
  profile (tabs, logins, cookies) persists on disk; they **cold-start into a
  free slot** on demand.
- **Capacity UX**: link click → slot free? browser spins up, viewer loads.
  All slots full → clear message: *"Browser fleet at capacity — try again
  later."* (Optional later refinement: queue position / agent retry — not in
  scope now.)
- **Reserved service slots**: `RESERVED_SERVICE_SLOTS` (e.g. 1 of 5) held
  for transversal agents (FR-14) — always on, never blocked by human
  saturation.
- **POC duty**: measure real RAM/CPU per running browser → set sensible
  defaults for the parameters.

## FR-8 Non-goals (unchanged)

- Not a VDI/remote-desktop product (browser only).
- We do **not build** a password manager — Vaultwarden stays the credential
  store; we **integrate** with it (FR-6).
- Not multi-tenant browser sharing: browsers are never shared **across**
  employees (one employee owns **one** browser — FR-2/FR-11 — but never a
  browser shared with another person).
- Not a multi-tenant platform: **sovereign single-tenant deployment (B3,
  2026-08-16)** — one client = their own server(s); isolation across clients
  is physical (separate servers), never logical. No cross-client fleet,
  routing, or data movement.
- Not an open-computer-use fork/embedding (license-clean by construction).
