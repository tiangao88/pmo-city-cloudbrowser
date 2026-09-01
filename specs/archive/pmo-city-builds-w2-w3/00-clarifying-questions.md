# Clarifying Questions — Cloud-Browser Service

> Status: **open**. Tigo answers in several steps. Answered items move to the
> relevant spec file; this file keeps the full history with answers noted.
> **2026-08-16 batch 2:** B3, C1, D1, D4, E3, I1, I2, I5 answered (sovereign
> single-tenant; Chromium only; full control MCP; EU residency on our
> infrastructure; 4-week MVP; downloads: both surfaces / flat area / always
> durable). **Batch 3 (fast ones):** A3, D3, E4, I3 answered. **Batch 4
> (final):** C2, D2, E1, F4, F6, F7, G1, G6, I6, J1, J2, J3 answered —
> **ALL QUESTIONS CLOSED (F8 default in spec, never needed a confirm)**.
> Spec is fully decided; only POC-validated values remain (viewer choice,
> capacity numbers).

---

## A. Naming (Tigo is picky here — domain first)

**A1. Domain name** — existing pattern is `*.pmo.city` (`ai-gw`, `memoviewer.dev01`, `secrets`…).
✅ **ANSWERED 2026-08-15:** `cloudbrowser.dev01.pmo.city` (dev); prod follows
pattern → `cloudbrowser.pmo.city`. (Voice said "pmo.ct" — read as `pmo.city`.)

**A2. Product name** — ✅ **ANSWERED 2026-08-15:** **Cloud Browser** — the
customer-facing name, shipped inside the PMO City solution (see B2).

**A3. Per-employee URL shape** — ✅ **ANSWERED 2026-08-16:** **per-user
subpath with short ID** — `cloudbrowser.pmo.city/u/<short-id>` (short ID
disambiguates same-name employees). No wildcard subdomains. Folded into
FR-1.

## B. Users & scope

**B1. First audience** — ✅ **ANSWERED 2026-08-15:** ① Tigo alone →
② Tigo + a few testers (PMO City teams) → ③ client teams, in the context of
the **MVP with Groupe Alsei**.

**B2. Product intent** — ✅ **ANSWERED 2026-08-15:** **sellable component of
the comprehensive PMO City solution**; our internally-developed bridge keeps
a **proprietary/commercial license** (MIT deps don't force MIT; AGPL Tinyauth
stays a separately operated service).

**B3. Multi-tenant** — ✅ **ANSWERED 2026-08-16:** **sovereign single-tenant
deployment** — PMO City is deployed on the client's own server(s): **one
client, one server, one deployment**. No shared fleet across companies.
Consequences: fleet capacity (FR-16) is per-deployment; isolation across
clients is physical (separate servers), never logical; per-deployment LLM
gateway (J2) confirmed; no cross-tenant routing ever (FR-15).

## C. Browser & UX

**C1. Engine** — ✅ **ANSWERED 2026-08-16:** **Chromium only** — the most
standard; browser-use/CDP integration is Chromium-family by design (FR-4).
Firefox out of scope for year 1.

**C2. Extensions** — ✅ **ANSWERED 2026-08-16:** **none preinstalled by
default** — clean profile, minimal attack surface. Per-user extension
installs possible later (out of year-1 scope). Folded into FR-2.

**C3. Viewer** — ✅ **ANSWERED 2026-08-16 (gate Q4):** agent gives a **link
in chat** → human clicks → opens in their device browser → the page **is the
browser** (the viewer). **Reuse an MIT viewer component** — do not develop
it. Mic/camera/audio **best-effort**, not a deal breaker. Component
evaluation: [09-viewer-evaluation.md](09-viewer-evaluation.md).

**C4. Downloads** — to user's device, server-side storage, or both? Retention?

**C5. Login/2FA handoff UX** — ✅ **ANSWERED 2026-08-16 (gate Q3):**
**hybrid** — TOTP if present in the share-vault item (broker enters it,
autonomous), otherwise the agent **asks in chat** and the employee reads the
code from their authenticator. User typing directly in the browser remains
available (FR-5).

**C6. Tabs** — ✅ **RESOLVED 2026-08-16 (gate Q1):** the **browser** has
**many tabs** (separation happens inside the single browser). The **viewer**
tab-bar UX remains an open detail for the POC (component-dependent, FR-15).

## D. Agent & security

**D1. MCP surface** — ✅ **ANSWERED 2026-08-16:** **full control** —
navigate/back/forward, click, type, scroll, extract, screenshot, **tabs,
downloads**. Everything a person can do (07-agent-api.md). Read-only mode:
deferred, addable later.

**D2. Agent binding** — ✅ **ANSWERED 2026-08-16:** **per-user only** — no
team/shared browsers in year 1 (service accounts are their own owner class,
FR-14). Folded into FR-4.

**D3. Audit** — ✅ **ANSWERED 2026-08-16:** **lean** — login/logout, attach,
browser destroy, downloads, broker login attempts + outcomes; **90-day
retention**; never page contents/credentials. Folded into FR-7.

**D4. Data residency** — ✅ **ANSWERED 2026-08-16:** **EU residency on our
infrastructure** — all PMO City servers/volumes (profile volumes, download
area, vault) live in the EU. **Scope note:** we guarantee *our*
infrastructure; we do not (and cannot) police which external websites or
third-party services the client's users visit — those may be outside the EU
(ties to B3: the client's server is wherever the client puts it; PMO City
requires an EU-located server).

## E. Ops & delivery

**E1. Deployment path** — ✅ **ANSWERED 2026-08-16:** **dev01 POC → prod via
Coolify as a new brick.** Folded into 08-roadmap.md.

**E2. Fleet sizing** — ✅ **ANSWERED 2026-08-16 (gate Q5):** **capacity
slots model** — `MAX_RUNNING_BROWSERS` (example 5) hard cap on running
browsers, per-container RAM limits (1–2 GB), unlimited parked (off)
browsers, `RESERVED_SERVICE_SLOTS` for transversal agents (FR-16). Actual
numbers set by POC measurement.

**E3. Timeline** — ✅ **ANSWERED 2026-08-16:** **MVP live within 4 weeks**
(by ~2026-09-13): W1 POC dev01 → W2 pilot (Tigo + testers) → W3 CRMOC teams
→ W4 Groupe Alsei MVP live (08-roadmap.md).

**E4. Spec language** — ✅ **ANSWERED 2026-08-16:** **English** — specs are
developed in English.

---

## F. Vaultwarden autonomous login (NEW requirement, captured 2026-08-15)

> Requirement as stated by Tigo: employees save their website credentials in
> **Vaultwarden** (per employee), and can **share them with their agent**; the
> agent then **logs in autonomously** to websites declared in Vaultwarden.

**⚠️ Security-model change to confirm:** the current design goal was
*"credentials-safe: user types passwords directly in the browser; the agent
only ever sees page state"*. Autonomous login via Vaultwarden means the agent
**reads credentials** (at least transiently, to fill the form). This is a
deliberate change — see F6.

**F1. Vaultwarden topology** — ✅ **ANSWERED 2026-08-15:** one **central**
agent-share Vaultwarden, **one OIDC setup**, **one organization** with **one
collection per employee** (each employee sees only their own collection).

**F2. Grant model** — ✅ **ANSWERED 2026-08-15 by Tigo:**
  - **(a) employee shares specific items with the agent (item-level share)** — OK
  - **(b) dedicated collection per employee** — OK
  - **(c) master password — REJECTED; solution = deterministic credential
    broker** (see below): the agent never receives the password at all; it
    only issues an intent, and deterministic software performs the login.

**F3. Autonomy level** — ✅ **ANSWERED 2026-08-15:** **configurable per-user
parameter**; default **(B) confirmation prompt** (early trust), switchable to
**(A) fully autonomous** once comfortable. Audit records which mode was active
per login.

**F4. Fill mechanism** — ✅ **ANSWERED 2026-08-16:** **CDP injection** — the
broker pushes credentials via the browser's native DevTools protocol. No
extension to build/sign/maintain; works with any Chromium; consistent with
C2. Folded into FR-9.

**F5. 2FA** — ✅ **ANSWERED 2026-08-16 (gate Q3):** **hybrid** — TOTP if
present in the share-vault item (broker enters it, autonomous), otherwise
the agent asks the user for the code in chat (FR-5).

**F6. Transient exposure** — ✅ **ANSWERED 2026-08-16:** **zero exposure via
FR-9 broker** — plaintext exists only inside the broker process, handed to
CDP; never in agent context, logs, or audit. Folded into FR-9 guarantees.

**F7. Password changes** — ✅ **ANSWERED 2026-08-16:** on a rotated/stale
password the agent **reports back to the employee** (\"login failed for
*site* — update the vault entry\") and the task **pauses**. No silent retry
loops (account-lock risk); the agent never updates the vault itself. Folded
into FR-6.

**F8. Declared sites** — "websites declared in Vaultwarden": the site URL in
the Vaultwarden item is the allowlist. Confirm no other declaration mechanism
needed.

---

## G. OIDC / token flow (NEW — from Tigo's proposal, captured as FR-10)

> Flow: employee logs into Vaultwarden with **Microsoft 365** (OIDC) → token
> stored with Hermes → deterministic broker uses token to log user into a
> site → agent drives the session. Feasibility confirmed (Vaultwarden OIDC +
> Entra ID documented). Open points:

**G1. Token custody** — ✅ **ANSWERED 2026-08-16:** **broker only** —
\"stored with Hermes\" = stored in Hermes' secret store, consumable **only
by the deterministic broker** (FR-9), never readable by the model. The
broker is a **software component** (no human role, no super-admin person) —
a deterministic \"vault clerk\" service deployed/operated by ops. Folded
into FR-9/FR-10.

**G2. Token scope acceptance** — ✅ **RESOLVED 2026-08-15 by design:** the
agent-facing Vaultwarden is a **dedicated share-vault** (not the employee's
daily Vaultwarden) containing **only** the passwords the employee wants to
share. A user-level token reading "everything in that vault" reads exactly
what was meant to be shared — no per-item scoping needed.

**G3. Vault topology (ties to F1)** — ✅ **ANSWERED 2026-08-15:** **central**
agent-share Vaultwarden, one OIDC setup, one org, one collection per employee.

**G4. Single IdP (OIDC)** — ✅ **ANSWERED 2026-08-15:** **one identity
provider for everything** — any **OIDC-compatible** provider (not necessarily
M365; M365/Entra is the concrete first). Vaultwarden uses OIDC; Tinyauth
**redirects to the same OIDC provider** → one login for viewer + MCP +
share-vault.

**G5. Token lifecycle** — ✅ **ANSWERED 2026-08-16 (gate Q2):** the browser
and session **never expire**; on token expiry the agent asks the employee
to **re-login in chat** (task pauses). **Transversal/service agents
(FR-14)** auto-refresh service tokens, never expire, alert **ops** on
failure. Logout is user-triggered only.

**G6. Broker auth to Vaultwarden** — ✅ **ANSWERED 2026-08-16:** **OIDC
session token** via the single IdP — preference over static API keys; no
second credential store. Folded into FR-9.

---

## H. Browser enumeration & attach (NEW — from Tigo, captured as FR-11)

> Requirement: employee lists **every browser where they are logged in** and
> **attaches to a particular one** from within a conversation. Ownership is by
> **immutable `user_id`**, never agent session ID. Open points:

**H1. Browser multiplicity** — ✅ **ANSWERED 2026-08-16 (gate Q1):** **ONE
browser per employee**, single instance, many tabs. No per-session
instances, no multiple profiles. (Future per-client multiplicity possible
under B3 — FR-11 keeps the API stable.)

**H2. Naming/labels** — ✅ **ANSWERED 2026-08-16 (gate Q1):**
**auto-generated, containing the username** — *"Browser — Stéphan"*.
Service browsers: *"Browser — CRM (service)"* (FR-14).

**H3. Attach semantics** — ✅ **RESOLVED 2026-08-16 (gate Q1):** with one
browser per user, any conversation resolves to **the user's browser**;
`browser.attach()` is a formality (FR-11). "Watch this browser" live mode =
the viewer (FR-15), always available alongside attach.

**H4. List contents** — ✅ **RESOLVED 2026-08-16 (gate Q1):** list returns
the **user's single browser** — id, auto-generated label (with username),
last-active, status running/sleeping (FR-11). Tab count/URL optional, POC
detail.

**H5. Logged-in definition** — ✅ **RESOLVED 2026-08-16 (gate Q1):** with
one browser per user, "where I'm logged in" = the employee's browser exists
(Tinyauth identity, authenticated at least once). Status
(running/sleeping) is separate from existence (FR-16 parked browsers).

**H6. Multi-device** — ✅ **RESOLVED 2026-08-16 (gate Q1/Q2):** one browser
per user → the **same browser** is attachable from any conversation/device
(that's the point: "whatever the session is using, it's a single browser").
Concurrent agent drivers on the same browser = POC detail (viewer watch +
agent control are both read/write on the same CDP target; sequencing to be
verified).

---

## I. Durable per-user download storage (NEW — from Tigo, captured as FR-12)

> Requirement: files saved from the various cloud-browser instances stay in a
> durable file system linked to the user's ID; the employee can find back
> every file downloaded from any instance. Open points:

**I1. Access surface** — ✅ **ANSWERED 2026-08-16:** **both** — (a) **file
browser in the viewer** and (b) **via the agent in chat** ("list my
downloads", "send me file X").

**I2. Storage shape** — ✅ **ANSWERED 2026-08-16:** **flat shared area** —
one per-user download folder across all tabs; same-name re-downloads get
suffixed (file.pdf → file (1).pdf). Per-instance folders obsolete (one
browser per user, gate Q1); per-tab/task folders possible later if ever
needed.

**I3. Quota & retention** — ✅ **ANSWERED 2026-08-16:** **5 GB per user**,
**90-day retention** with auto-purge of files older than 90 days, **GDPR
erasure** on user delete. Folded into FR-12.

**I4. Agent access** — ✅ **ANSWERED 2026-08-15:** the durable file system
**is accessible to the user's Hermes agent**, so the agent can work on the
downloaded files (read, process, summarize, re-send).

**I5. Download routing** — ✅ **ANSWERED 2026-08-16:** **always** — the
browser's download directory **is** the per-user durable volume; automatic,
no per-download decision (FR-12).

**I6. Security/residency** — ✅ **ANSWERED 2026-08-16:** residency per D4
(EU hosting on our infrastructure); **virus scanning YES — scan at ingest**,
flagged files quarantined, user notified (ClamAV default). Folded into
FR-12.

---

## J. Configurable LLM connectivity (NEW — from Tigo, captured as FR-13)

> Requirement: the cloud browser runs in a separate container and may require
> LLM access; everything must be configurable, pointing at the OmniRoute AI
> proxy so LLM configuration is deployment-configurable. Open points:

**J1. LLM consumers in the container** — ✅ **ANSWERED 2026-08-16:**
browser-use **agent mode only** — the harness itself needs no LLM (the agent
writes the scripts); no other in-container path needs LLM in year 1. Folded
into FR-13.

**J2. Per-deployment proxy** — ✅ **ANSWERED by B3 (2026-08-16):** each
client deployment points at **its own LLM gateway** (sovereign single-tenant
— no shared multi-tenant proxy routing). Folded into FR-13.

**J3. Config mechanism** — ✅ **ANSWERED 2026-08-16:** **env-file refs**
(`${VAR:-default}`, matching the rest of the compose stack) — no baked
config values, secrets via env refs. Folded into FR-13.
