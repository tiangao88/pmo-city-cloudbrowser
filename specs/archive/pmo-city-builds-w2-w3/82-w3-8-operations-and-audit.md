# W3-8 — Operations, audit, retention, and response

Date: 2026-08-31
Status: **COMPLETE — documentation and contract checks verified locally; no
production or fleet deployment performed.**
Scope: CloudBrowser dev brick and its future sovereign single-tenant install.
Depends on: `08-roadmap.md`, `28-w3-scope.md`, `31-queue-and-session-limits.md`,
`42-session-isolation-fix.md`, `43-session-isolation-tests.md`, `56-identity-cookie-strip.md`,
`61-tab-loss-hardening.md`, `77-w2-recreate-recovery.md`, and
`81-w3-1a-identity-queue-reconciliation.md`.

## 1. Decisions and boundaries

- The router, slot restart API, Neko viewer, broker, and janitor remain separate
  operational components. Health must be checked at the component boundary, not
  inferred from the outer HTTP page alone.
- The audit surface is an operational record, not a browser recording or a
  credential store. It records what happened, which owner/slot/request was
  involved, and the outcome; it never records secrets or page contents.
- User identity is the authenticated request identity or the server-derived
  current slot owner. A caller-supplied identity that disagrees with the
  server-derived owner is an `owner_mismatch` failure.
- A healthy infrastructure response does not prove an authenticated application
  surface. W3-1 must separately verify owner binding, browser readiness, broker
  re-login, and visible identity.
- This document defines runbooks and acceptance evidence. It does not authorize
  a deploy, a fleet restart, a credential rotation, or a business-data write.

## 2. Lean audit record

### 2.1 Event envelope

The existing service logs may remain the transport during the dev phase; a
central sink is a W4 installation choice. Every event must be written as a
structured single-line record when a structured audit adapter is enabled.

```json
{
  "schema": "cloudbrowser.audit.v1",
  "event_at": "2026-08-31T00:00:00Z",
  "event_type": "slot_wake",
  "request_id": "opaque-request-id",
  "actor_type": "router|user|agent|operator|system",
  "owner_id": "user@example.com",
  "slot_id": "slot-1",
  "session_id": "opaque-session-id",
  "reason": "idle|released|expired|rescue|recreate|queue",
  "outcome": "started|completed|rejected|failed|skipped",
  "error_code": null,
  "duration_ms": 4200
}
```

Required fields:

- `schema` — fixed version identifier;
- `event_at` — UTC event time, with synchronized host/container clocks;
- `event_type` — bounded event name, such as `queue_enqueue`, `queue_offer`,
  `queue_take`, `slot_wake`, `slot_suspend`, `slot_rescue`, `slot_recreate`,
  `broker_login`, `broker_login_failed`, `archive_write`, `archive_restore`,
  `retention_purge`, or `operator_action`;
- `request_id` — opaque correlation value; do not use a bearer, cookie, or URL
  containing credentials;
- `actor_type`, `owner_id`, and `slot_id` — only where known and authorized;
- `outcome` — one of `started`, `completed`, `rejected`, `failed`, or `skipped`.

Optional fields are limited to `session_id`, a bounded `reason`, a bounded
`error_code`, and non-sensitive duration/count values. Do not add arbitrary
request headers, URLs, page text, filenames, DOM, screenshots, or exception
strings to the schema.

### 2.2 Explicitly prohibited values

Never put any of the following into stdout, the audit record, router state
summaries, model context, tickets, or operator evidence:

- passwords, Neko query-string passwords, refresh/access tokens, API keys,
  bearer values, TOTP seeds, one-time codes, or private keys;
- SSO cookies, cookie values, browser storage, grant material, decrypted vault
  fields, or credential-bearing page content;
- complete authorization headers, raw query strings, arbitrary URLs, DOM,
  screenshots, downloads, CRM data, or message bodies;
- full filesystem paths when they reveal tenant/user secret layout beyond the
  minimum operator need.

Email identities may be recorded only where the control-plane contract already
uses an authenticated user identity. Normalize them exactly as the service
currently does; never treat a displayed label as proof of backend ownership.

### 2.3 Audit examples

Safe examples:

```text
cloudbrowser.audit.v1 event_type=slot_wake owner_id=user@example.com slot_id=slot-1 outcome=completed reason=idle
cloudbrowser.audit.v1 event_type=slot_rescue owner_id=user@example.com slot_id=slot-1 outcome=rejected error_code=owner_mismatch
```

Unsafe examples that must not be emitted:

```text
POST /?pwd=...&usr=user@example.com
Authorization: Bearer ...
tinyauth-session-...=...
```

The router already strips request query strings from its operational request
log. That rule remains mandatory for every new endpoint and audit adapter.

## 3. Health model

Health is layered. Check in this order and report the first failed layer:

1. **Coolify/service layer:** the intended resource and its applications are
   running and healthy; confirm the deployed image/config revision.
2. **Router layer:** `GET /health` returns `{"ok":true}`; `GET /fleet/status`
   is readable only through its intended internal control boundary.
3. **Slot layer:** each relevant slot `GET /health` reports the expected owner,
   `suspended` state, `cdp_ok`, and `google-chrome` state. A slot is ready for
   an owner only when `suspended=false`, `cdp_ok=true`, Chrome is `RUNNING`, and
   the reported `user` matches the requested owner.
4. **Surface layer:** the queue/landing/session response identity matches the
   authenticated request identity. `/queue/status` and `/fleet/my-status`
   must agree on active/waiting/offered/backed-off state. An `owner_mismatch`
   is a fail-closed outcome, never a routing hint.
5. **Application layer:** the trusted application page and broker result are
   owner-bound. Infrastructure health alone is not an authenticated-surface
   pass.

The two existing read-only endpoints are complementary: `/fleet/status` is an
operator/control-plane snapshot; `/fleet/my-status` is the caller-keyed status
view. Never use an operator snapshot to substitute an identity in a user page.

## 4. Recovery and operator response

### 4.1 First response

1. Record UTC time, affected surface, authenticated request identity, slot, and
   safe status JSON. Use an opaque request correlation value.
2. Compare router `/fleet/status`, caller `/fleet/my-status`, queue `/queue/status`,
   and the slot `/health`. Do not capture cookies, tokens, OTPs, passwords, or
   page contents.
3. If owner, slot, or queue state disagrees, stop routing the request and treat
   it as an identity-boundary incident. Do not manually open tabs or copy a
   profile to investigate.
4. Check whether the failure is infrastructure-only (router/slot/CDP) or an
   authenticated-surface failure (broker/visible identity). Do not report the
   former as proof of the latter.

### 4.2 Safe recovery order

- **Queue/identity mismatch:** fail closed; keep the caller queued or return the
  documented `backed_off`/error state. Do not substitute another user or
  silently route to a stale page.
- **Chrome/CDP unhealthy:** use the slot's owner-bound `POST /restart` or
  recovery path; verify `/health` and the owner match before allowing landing,
  proxying, or queue activation.
- **Viewer stream/login wedge:** use `/fleet/rescue` for the current owner;
  respect the circuit-breaker budget and cooldown. After a rescue cap, the
  assignment is terminal for that episode and must not be routed back into the
  same broken viewer.
- **Idle suspend:** use the existing `/release` → archive → owner-aware wake
  path. An idle archive may resume; `released`, `expired`, and offer-expiry
  paths must preserve their queue semantics.
- **Container/service recreate:** verify all applications, then inspect the
  owner-bound boot hint and slot readiness. The boot hint may dispatch the
  standard `/wake` only after confirming the owner is not active elsewhere.
- **Archive or snapshot anomaly:** stop profile swapping, preserve the current
  evidence, and use the owner marker plus the last-good snapshot policy. A
  malformed live snapshot may fall back to last-good; a valid empty workspace is
  authoritative. Owner mismatch clears/blocks both snapshot copies.
- **Viewer loading failure:** a Chrome/Vulkan or title-proxy failure is an
  infrastructure/viewer incident. Validate the proposed Chrome flags in an
  isolated dev change before rollout; do not claim W3-1 authenticated continuity
  from a spinner or outer page response.

### 4.3 Closure criteria

Close an incident only after the affected path has a read-back showing:

- the expected server-derived owner and slot;
- `suspended=false`, `cdp_ok=true`, Chrome `RUNNING` where a live slot is
  required;
- queue/status/page identity agreement;
- no foreign tabs, archive marker, history, cookies, or grant material;
- a bounded audit event with outcome and correlation, containing no secret;
- focused regression coverage if code changed.

If any item is not proven, leave the incident open as `not_proven` rather than
marking it green.

## 5. Retention and erasure review

### 5.1 User files

The existing user download policy remains **5 GB per user with 90-day
retention**. `janitor.py` scans at ingest, quarantines a positive ClamAV result,
purges files older than `RETENTION_DAYS` (default 90), and enforces quota in
its configured purge mode. The janitor state file is operational state, not an
audit substitute. Quarantine handling must follow the same tenant/user access
boundary and must not be presented as a clean user download list.

### 5.2 Audit records

Audit records use a separate lifecycle from browser profiles and user files:

- retain the minimum secret-free operational events for **90 days** by default;
- keep timestamps in UTC and use an immutable/append-only sink where the
  deployment supports it;
- restrict read access to the minimum operations role; users do not receive
  another user's operational events;
- rotate/archive before purge if the tenant's approved legal/incident policy
  requires a hold;
- delete or cryptographically render records unavailable at expiry, except for
  an explicitly documented legal/security hold;
- record only aggregate purge counts and the policy version after deletion;
- test expiry with synthetic records before enabling any destructive production
  cleanup.

This is an operational default, not legal advice. GDPR erasure requests must
remove user-identifying operational records where required, subject to a
 documented legal/security hold and the tenant's approved retention policy.
The retention decision must be recorded per sovereign tenant before W4 go-live.

### 5.3 Browser profiles and archives

Browser archives are user state, not audit records. Their lifecycle follows the
per-user archive/erase contract: no identity cookies are archived/restored;
profile swaps require Chrome and title-proxy to be stopped; owner markers and
last-good snapshots are checked during recovery. A user-delete operation must
remove that user's profile/archive and downloads through the approved erasure
procedure, with a secret-free completion event.

## 6. Operator checklist

- [ ] Confirm target environment and tenant; no production action by default.
- [ ] Capture only sanitized status JSON and UTC time.
- [ ] Check router, slot, queue, and surface layers in order.
- [ ] Verify owner identity from the server, not from a stale page or cookie.
- [ ] Preserve per-user isolation and fail closed on mismatch.
- [ ] Use the narrowest recovery endpoint and respect cooldowns/circuit breakers.
- [ ] Read back health and ownership after every state-changing recovery call.
- [ ] Record a secret-free audit outcome and bounded error code.
- [ ] Escalate unproven authenticated continuity; do not silently downgrade it.

## 7. W3-8 acceptance record

- [x] Lean audit schema expanded with owner/slot/request/lifecycle outcome
      fields and explicit secret exclusions.
- [x] Health layers and readiness contract documented.
- [x] Recovery and operator response paths documented, including fail-closed
      identity handling and viewer failure handling.
- [x] 90-day user-file policy and separate 90-day audit lifecycle reviewed;
      erasure and legal-hold boundary recorded.
- [x] W4 checklist is in `83-w4-sovereign-installation-checklist.md`.
- [x] No live deployment, fleet restart, browser mutation, or business-data
      write performed for W3-8.
