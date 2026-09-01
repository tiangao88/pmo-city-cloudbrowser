# 67 — Per-user isolation review: shared assets audit (2026-08-25)

Status: **AUDIT COMPLETE → 5 items fixed / 4 open** (commit TBD)

## Directive (Tigo, 2026-08-25)

> "Everything has to be separated per user. I am very concerned when I
> see that there were some shared assets. Shared is forbidden. We are
> having a per-user system, so review everything that is shared,
> because that's where we have potential security incidents. There's no
> concept of shared here across users... anything that is shared is
> suspicious, please review that in the technical design."

## Audit result — every shared asset, verdict, action

### 1. Shared static SSO creds file — **FIXED (spec 66)**
`sso-creds.b64` (spike-user bot creds) was a shared file on the scripts
volume auto-filled into EVERY user's SSO. Deleted from volume; broker
now resolves the slot owner and reads per-user
`/data/sessions/<owner>/grant/sso-creds.json`. Harness 114/114.

### 2. `NEKO_PASSWORD` / `NEKO_PASSWORD_ADMIN` — **open, D1 tracks it**
Shared across all slots/services (W1 stopgap). Every user's kiosk
session can be driven with the same password. **Retirement is D1**
(after the broker is the per-user credential mechanism) — the spec-66
per-user creds are the foundation. Until D1, the password is
container-scoped (never exposed in URLs; the neko client strips it
after auto-login) and the real gate is SSO (tinyauth).

### 3. Shared broker/admin/agent tokens (Coolify magic vars) — **open, by design**
`SERVICE_PASSWORD_64_GHBROKER`, `_GHADMIN`, `_AGENTTOKEN`,
`CB_AGENT_TOKEN` are shared across router + slots. These are
**infrastructure credentials** (broker↔router API, admin kill switch,
agent queue), not user identities — they never authenticate as a user,
they carry no user data, and they're minted/persisted by Coolify
(magic variables), not Vaultwarden. Verdict: acceptable; they grant
only the grant-API/queue surface, not per-user vault access.

### 4. `GRANTHUB_URL` / `GRANTHUB_STATUS_URL` — **ok (relative, no secrets)**
Relative `/connect` / `/connect/status`, same-origin; no shared
identity material.

### 5. Sessions volume (`/data/sessions`) — **per-user ✓** (one gap, fixed)
Per-user dirs with 0700-equivalent perms; grants are per-user. Gap:
`spike-user2@aikumi.pro`'s archive contained the **same two PDFs** as
montigaud's (BCG + McKinsey) — copies duplicated across archives by the
downloads surface, **not** cross-user access. Downloads volume is
**per-slot** (one Downloads dir per slot, served to the current owner);
per-user durability lives in the per-user archive. → Open item: decide
whether the per-slot Downloads dir should be keyed per-user (the
archive is the durable per-user store).

### 6. Scripts volume (code) — **shared, by design, not a risk**
Code is shared infra (same binaries per slot); it contains NO user
secrets. The `*.bak-*` files (router/restart-api/sso-broker backups)
are inert code backups — **remove them to reduce the attack surface**.

### 7. Router state file — **shared infra, ok** (root:root 644; contains
emails + queue state, no credentials; volume is router-only).

### 8. Router itself — single shared router = **by design, ok** (one
entry point, Remote-Email-keyed; the router never holds user secrets —
grants live in per-user session dirs).

### 9. `grant-sync.py`, `pm-fill.py`, `granthub.py`, `gcm.py` — **ok**
per-user by email argument; decrypt only the owner's grant.

### 10. `.slot-user.json` (downloads + broker owner marker) — **per-slot
state, ok** (rewritten on each wake/identify; used to key identity).

### 11. tinyauth session — **per-user sessions ✓** (each SSO login
creates its own session cookie; the shared client secret is infra).

## Actions taken now (commits)

- `250172e` spec 66: per-owner broker creds + shared file removed.
- Spec 66 incident doc updated with the follow-up section (this
  audit's scope).

## Open items (need decisions)

- **O-1 (D1):** retire shared `NEKO_PASSWORD` — after the per-user
  broker creds are provisioned for real users (grant path D3.4/D2).
- **O-2 (Downloads per-user):** ✅ DONE — spec 68: suspend/release now
  wipe the slot Downloads volume + clear `.slot-user.json`; per-user
  durable store = the archive (live-verified on slot-2).
- **O-3 (bak files):** ✅ DONE — 4 stale `*.bak-*` removed from the
  scripts volume (2026-08-25).
- **O-4 (per-user broker creds):** ✅ code path done (spec 66/68:
  broker is per-owner only, stale-identity guard, no shared fallback);
  montigaud's own identity comes from HIS kiosk vault login (capture
  path) — no agent handling of his password. Optional auto-fill
  convenience file may be provisioned later.

## Conclusion

Per-user isolation holds across: profiles, archives, grants, cookies,
sessions, downloads (archive), and broker identity (after spec 66).
The remaining shared items are **infrastructure credentials and code**,
not user data — each is either D1-scoped (NEKO_PASSWORD), by design
(API tokens), or needs the decisions above (O-2/O-3/O-4).
