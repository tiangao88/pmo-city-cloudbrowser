# Decision Gate 2 — 5 More Questions Before Implementation

> Status: **CLOSED — all 5 answered 2026-08-16**. Each answer is folded into
> the specs (FR-2/FR-5/FR-6/FR-10/FR-11 updated; FR-14 transversal agents,
> FR-15 viewer, FR-16 capacity added; batch C/E/F/G/H updated in
> [00-clarifying-questions.md](00-clarifying-questions.md); viewer component
> research in [09-viewer-evaluation.md](09-viewer-evaluation.md)). Gate 1
> (naming, share-vault topology, licensing/audience, autonomy level, single
> IdP) is **CLOSED** — see [decision-gate.md](decision-gate.md).

---

## Q1 — Browser multiplicity (H1/H2)

**Status: ✅ ANSWERED 2026-08-16 — ONE browser per user, period.**

- **Single instance per employee**, owned by the immutable `user_id` —
  whatever session or conversation asks to view the browser, it is **the same
  browser**. No per-session instances, no multiple profiles.
- **Tabs carry separation**: the one browser has **many tabs** — that is how
  the employee separates contexts (work / client A / personal), all inside
  their single browser.
- **Naming**: **auto-generated, containing the username** — e.g.
  *"Browser — Stéphan"* — so it is unmistakably *his*: it holds his
  credentials, everything inside is his.

**Folded into:** FR-2 (one browser per employee), FR-11 (list returns at most
one browser; attach becomes a formality), batch H.

---

## Q2 — Re-login / token lifecycle (G5)

**Status: ✅ ANSWERED 2026-08-16 — never expire; expiry is user-triggered
for people, absent for service agents.**

- **The browser never expires. The session never expires.** No inactivity
  TTL, no auto-logout, ever.
- **If a token expires** (Vaultwarden/IdP): the agent **asks the employee to
  re-login** in chat (link, one tap). The task pauses until they
  re-authenticate. No silent refresh of personal credentials behind the
  user's back.
- **Logout is user-triggered only**: "log me out, destroy my browser" →
  the browser profile is wiped (cookies, cache, stored credentials).
  **Downloads survive** in the durable per-user file area (FR-12) — they are
  separate from the browser.
- **NEW — transversal agents (discovered in this answer):** service-owned
  browsers with **no human owner** (e.g. the company CRM agent needing access
  all the time). These **never expire and never pause**: service-level tokens
  **auto-refresh**; if refresh fails, it alerts **ops**, not a chat.
  Ownership key = **service account** (e.g. `svc-crm`), own **collection** in
  the same central share-vault. Isolation unchanged: employees never see
  them, they never see employees' browsers. See FR-14.

**Folded into:** FR-10 (token lifecycle), FR-14 (transversal agents), G5.

---

## Q3 — 2FA on websites (F5/C5)

**Status: ✅ ANSWERED 2026-08-16 — Hybrid: TOTP if present, chat prompt
otherwise.**

- **TOTP present** in the share-vault item → the **broker** enters the code
  (fully autonomous; employee enabled TOTP once).
- **No TOTP stored** → the agent **asks in chat**; the employee reads the
  code from their authenticator and the broker/employee enters it.
- Never a hard block, never autonomous 2FA without the stored secret.

**Folded into:** FR-5, FR-6, F5, C5.

---

## Q4 — Viewer scope & UX (C3/C6)

**Status: ✅ ANSWERED 2026-08-16 — link-click viewer; reuse an MIT component;
mic/camera/audio best-effort.**

- **Flow**: the agent gives a **link in chat** → the human clicks → it opens
  in **their own device browser** → the page that loads **is the browser**
  (the viewer).
- **Do not develop the viewer**: reuse an **MIT viewer component** —
  definitely wanted if one exists.
- **Audio/mic/camera**: good to have **from the beginning** (meet calls) —
  but **only if found inside an MIT viewer component**; best-effort, **not a
  deal breaker**.

**Viewer component research (2026-08-16):** no single turnkey MIT viewer with
mic+camera+audio exists today. Closest: **noVNC (MPL-2.0, page-only, no
audio)** and **neko (Apache-2.0, WebRTC + built-in audio, mic input open
issue)**. KasmVNC is **GPL-2.0 → excluded**. Full evaluation + POC spike
plan: [09-viewer-evaluation.md](09-viewer-evaluation.md).

**Folded into:** FR-15, C3, C6 (partial).

---

## Q5 — Fleet sizing & timeline (E2/E3)

**Status: ✅ ANSWERED 2026-08-16 (capacity model) — parking-spot fleet.**

- **Finite concurrent slots, unlimited parked browsers:**
  - the fleet has a fixed number of **"on" slots** (parameter
    `MAX_RUNNING_BROWSERS`, example **5**) — a hard cap on simultaneously
    running browsers, enforced by **per-container RAM limits** (1–2 GB each),
    so one browser can never starve the server;
  - any number of browsers can **exist but be "off"** — their profile (tabs,
    logins, cookies) persists on disk; they **cold-start into a free slot**
    on demand.
- **Human experience**: link click → free slot? browser spins up → viewer
  loads. **All slots full?** clear message: *"Browser fleet at capacity —
  try again later."* (Optional later refinement: queue position / agent
  retry — not now.)
- **Service guarantee**: transversal agents get **reserved slots**
  (`RESERVED_SERVICE_SLOTS`, e.g. 1 of 5) — never given to humans, always
  on, never blocked by capacity.
- **Timeline / deployment path (E1/E3): still open** — Tigo answered the
  capacity model; target dates for POC/MVP and the Coolify deployment-path
  confirmation remain pending.

**Folded into:** FR-16 (capacity management), E2 answered / E1/E3 open.

---

## Gate 2 — summary of decisions

| # | Decision | Status |
|---|---|---|
| Q1 | **One browser per employee**, single instance, many tabs; auto name with username | ✅ |
| Q2 | **Never expires**; re-login prompt on token expiry; logout user-triggered; **transversal agents always on** | ✅ |
| Q3 | **Hybrid 2FA** — TOTP if present, chat prompt otherwise | ✅ |
| Q4 | **Link-click viewer**, reuse MIT component, mic/cam/audio best-effort | ✅ |
| Q5 | **Capacity slots** — `MAX_RUNNING_BROWSERS` + RAM caps + reserved service slots | ✅ (E1/E3 open) |

**Three validations from the Q2 proposal** (kept as proposed — no objection
raised before GO): ① "destroy my browser" wipes the profile but **keeps
downloads**; ② transversal agents get a **service account + own collection**
in the same central vault; ③ naming **"Browser — Stéphan"** / **"Browser —
CRM (service)"**.
