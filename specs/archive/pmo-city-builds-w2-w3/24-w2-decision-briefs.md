# W2 Decision Briefs (24)

> Drafted 2026-08-19 (Tigo: "ok draft the decision briefs"). One brief per
> open decision; each = context · options · recommendation · needs from Tigo.
> Tigo decides one-by-one; agent waits for "go" before executing any option.
> Companion to `20-w2-dod.md` §4 (open points) and `21-w2-autonomy.md` §4
> (A1/A2/A3/A7).

---

## Brief A1 — Per-user browser wiring (D1)

**Decision needed:** how a per-user link maps to a browser instance (FR-1:
per-employee browser, immutable `user_id`, short-id).

**Context:** pilot = Tigo + testers (2–4 browsers). Each instance needs: own
Chrome profile volume (tabs/cookies persist — D5 pattern), own env
(`user_id`, screen), own URL, SSO as that employee, RAM cap 2 GB (D9
pattern), and the full verified stack (tabbar, broker, downloads-api,
restart-api).

**Options:**

1. **Coolify clone-per-user** (recommended for the pilot) — clone the viewer
   service per pilot user; per-user env + own domain
   `browser-<short>.dev01.pmo.city`; name "Browser — <name>".
   - ✅ Real isolation (per-user volume, per-user RAM cap, per-user SSO)
   - ✅ Reuses every verified component as-is (zero new dev)
   - ✅ Matches the production mental model
   - ⚠️ N services in Coolify; ~0.5–1 GB idle RAM each (2–3 testers ≈ 2–3 GB
     on dev01 — acceptable; dev01 has no cap but each instance gets its own)
2. **Single service, compose profiles per user** — one Coolify service,
   profile per user.
   - ⚠️ Coolify compose renderer + UI-managed domains fight per-profile
     routing; label-dedup footgun already burned us once → fragile
3. **Orchestrated on-demand instances** (true production shape) — fleet gate
   (:9230) spawns/stops a container per user link.
   - ✅ Resource-efficient, production shape
   - ⚠️ Lifecycle + persistence design to build; most dev time; overkill for
     pilot

**Recommendation:** Option 1 for the pilot; Option 3 recorded as the
production evolution (designed later, not built now).

**Needs from Tigo:** (a) approve Option 1; (b) pilot user names + group
memberships.

---

## Brief A2 — Test identities (D2/D3/D10)

Three sub-decisions, one pass:

**a) Vaultwarden test items (D2 — hybrid 2FA).** Per-pilot-user login items
in the share collection: test creds for the CRM test account (or a sandbox
site) + TOTP seed where the TOTP leg is exercised.
- Agent creates (G2 grant) with values you approve → you just eyeball the
  list, or
- You create them yourself (same as the W1 test item) — slower but zero
  surprise.
- **Recommendation:** agent creates; you approve the values before use.

**b) IdP test OIDC client (D3 — broker OIDC session flow).**
- Reuse the existing cloudbrowser app + `spike-user` (both groups, proven),
  or
- Dedicated `cloudbrowser-broker` test client on Authentik + `spike-user` as
  test user (isolates broker-flow testing from the kiosk app).
- **Recommendation:** dedicated client, `spike-user` as test user — you or an
  admin creates the client (Authentik app creation is admin-side).

**c) Denial-path account (D10/A3).** Any account NOT in `PMOC_Users`.
- Re-use `nico.verdi` (already removed from the group, denial screenshots
  exist) if he is still a real Aikumi Connect user, or
- Create `spike-deny` (clean, dedicated, no dependency on a real person).
- **Recommendation:** `spike-deny` — zero coupling to a real account; you or
  an admin creates it.

**Needs from Tigo:** approve a/b/c (one reply covers all three).

---

## Brief A7 — Screen-follow approach (D13)

**Decision needed:** does the visible screen follow the agent's actions
(active tab / scroll) during the pilot, and how?

**Context:** D7 = fixed kiosk canvas (done). D13 = follow. Register noted
"neko v3 feature or custom bridge"; the pinned image is neko **2.9.0** —
v3 features are not guaranteed to exist there.

**Options:**

1. **Native neko follow if present in 2.9.0** — zero new code; but if absent
   → upgrading neko = new image = re-verify D11 drift pin + branding + tabbar
   overlay (regression risk, real cost).
2. **Custom bridge (broker/title-proxy pattern)** — small CDP watcher that
   mirrors the agent's tab/scroll moves onto the neko viewport. Works on
   2.9.0, reuses verified patterns; new component to maintain, scroll
   fidelity needs care.
3. **Defer D13 to W3/production** — kiosk stays for the pilot; follow is a
   demo nicety, not a pilot blocker (log-me-in + see-the-browser work
   without it).

**Recommendation:** (1) run a 30-min zero-risk capability probe on the
pinned 2.9.0; (2) then: native follow if it exists, else custom bridge
**if** you want it in-pilot, else defer to W3. Sequencing: after D7, never
blocks D1/D2/D3.

**Needs from Tigo:** approve probe-first; choose defer-now vs bridge-now for
the pilot.

---

## Summary of asks (single reply each)

- **A1:** approve clone-per-user + pilot names/groups
- **A2:** approve a/b/c (vault items · IdP client · denial account)
- **A7:** approve probe-first + defer vs bridge
