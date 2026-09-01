# 74 — D2 deployment and qualification evidence

Date: 2026-08-26 · Fleet: `cb-fleet-v2` (`okixw2fxnwn1lakxvxajodww`)

## Scope deployed

- Prompt tab restoration on wake (`restart-api.py`, commit `a309fe5`).
- D2 hardening: exact Authentik 2025.8.1 DOM/TOTP-device checks;
  generation-bound owner handling; exact vault-item selection; canonical
  identities and contained paths; per-slot broker tokens; router-only grant
  store; slot-authenticated grant material and refresh-token persistence;
  opaque one-shot OTP challenges.
- Chrome policy/customization fail-closed startup remains enabled.

## Pre-deployment qualification

- Router regression: **114/114 PASS**.
- D2 suite: **6/6 PASS**.
- Slot isolation/security: **2/2 PASS**.
- GrantHub regression: **34/34 PASS**.
- Authentik exact-DOM/device guard: **PASS**.
- Prompt restore regression: **PASS**.
- Restart tab snapshots: **3/3 PASS**.
- Ownerless-slot recovery: **PASS**.
- Python compilation and `git diff --check`: **PASS**.

## Deployment

1. Updated the Coolify service compose from the repository spec.
2. Installed the repository scripts into the service's shared scripts volume;
   SHA-256 values were verified on the host before restart.
3. Triggered a full Coolify deployment of the authorized service.
4. Waited for router, both slots, janitor and ClamAV to report healthy.

## Live qualification

- Coolify service: `running:healthy`; all five components healthy after the
  deployment.
- Router and both restart APIs answer health checks.
- Slot 1 restored MontyGo's three saved tabs immediately after service start;
  this exercises the prompt-restore code path that previously waited for the
  30-second watchdog.
- Both slots have the Chrome policy gate and customization receipt for CfT
  `128.0.6613.137`, extension `1.13.1`, with password storage
  `disabled-and-purged`.
- Slot 2 was explicitly sanitized after qualification and returned to
  `suspended:true`, ownerless, Chrome stopped.
- Runtime environment includes the per-slot token and grant/OTP endpoint
  variables required by D2. No credential values were logged or recorded.

## Live issue found during autonomous qualification

At 2026-08-26 13:45 UTC, spike-user took slot 1 and reached the Authentik login
page. The broker repeatedly reported a grant-material HTTP error and could not
load the current owner's login item.

Root cause: the slot-side `vault_client.py` correctly calls
`GET /connect/grant/material` with only its per-slot bearer, but the router's
global SSO gate and `_broker_identity()` still required `Remote-Email`. The
production request therefore returned 401 before the slot-token identity check.
The original isolation test only exercised a request that supplied
`Remote-Email`, so it did not represent the real slot client.

A RED regression now covers the exact production shape: per-slot bearer with no
identity header. The router dispatches this endpoint before the external SSO
email gate, derives the current owner exclusively from the per-slot bearer and
router state, forbids the legacy shared token, and rejects any optional identity
header that conflicts with the server-derived owner. Post-fix suites remain: router **114/114**, D2 **6/6**,
isolation/security **2/2**, and GrantHub **36/36** (including controlled
missing-session-leg recovery and restoration).

The router fix was installed in the shared volume and loaded by the live router.
The first user's offer expired during the router restart, so live autonomous
qualification must resume when spike-user is offered the slot again.

## D2 completion boundary

**D2 is live-qualified and closed.** The fleet is `running:healthy`; GrantHub
is `shared:true`, `session:true`, `usable:true`; and the exact vault selection
is `Aikumi Connect` on both slots.

Live evidence captured on slot 1 for `spike-user@aikumi.pro`:

1. **Grant/autonomous credential path:** the broker fetched the current owner's
   exact item through the per-slot bearer path and logged `creds loaded for slot
   owner ... (grant path)`, `login tab detected — attempting broker login`, and
   `filled + submitted`.
2. **No-seed/chat-assisted path:** after CDP confirmed the live Authentik
   `deviceClass=totp` stage, a fresh opaque request was bound to slot 1 and the
   current owner. The employee supplied the current authenticator code in chat;
   the agent-only endpoint accepted it once, the slot fetched it once, and the
   code was removed immediately after fill. Authentik accepted it and the tab
   left the auth origin. Broker evidence: `login attempt finished OK (MFA)`.
3. **Fail-closed controls:** missing session legs now return controlled
   `GrantError`; refresh-token rotation POSTs are owner-bound by per-slot bearer;
   replay/cross-slot/owner-reassignment controls remain green in the deployed
   isolation/security regression.

No credential, refresh token, seed or one-time code was written to repository
evidence or emitted in service logs. Temporary code payloads were deleted after
the one-shot exchange.
