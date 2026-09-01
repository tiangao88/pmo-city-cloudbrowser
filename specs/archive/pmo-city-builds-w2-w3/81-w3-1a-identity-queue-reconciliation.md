# W3-1A — Identity and queue-state reconciliation

Date: 2026-08-29
Status: **IMPLEMENTED — local readiness and regression verification complete; live two-browser observation pending. W3-1 parent remains blocked by authenticated-surface continuity.**
Owner: CloudBrowser platform
Parent: `28-w3-scope.md` → W3-1

## Purpose

Close the gap exposed by the two pilot screenshots: the main-browser TinyAuth
identity can be valid while the CloudBrowser queue page displays a stale or
incoherent state (`?`, the wrong queued identity, or an active session that is
not reflected after reload).

This is a W3-1 subtask, not a new W4 feature. It covers the identity boundary
between the TinyAuth `Remote-Email` header, router-owned slot/queue state, and
the embedded Chrome surface. It does not weaken spec-56 identity-cookie
stripping or claim that a main-browser SSO cookie authenticates the embedded
Chrome application.

## Local readiness-barrier implementation

The router now treats a slot assignment as unusable until the slot restart API
reports all of the following for the requested owner: `suspended=false`,
`cdp_ok=true`, `google-chrome=RUNNING`, and a matching `user`. Fresh
assignments and persisted active-session reloads both pass this barrier; a
suspended slot is woken and polled until ready. Failed or timed-out readiness
rolls the assignment back and returns the caller to the queue. Queue polling
uses the same barrier, so it cannot advertise `active` before Chrome is usable.

Local evidence:

- `test-router-w31.py`: **127 passed, 0 failed** (complete staged router harness).
- `test-router-w31-readiness.py`: **2/2 passed** (fresh assignment and
  assigned-but-suspended entry).
- `test-w3-1a-queue-reconciliation.py`: **19 checks passed**.
- `test-w3-1a-status-readiness.py`: **passed** (queue poll fails closed before
  readiness).
- `test-w3-1a-source-contract.py`: **7/7 passed**.
- `test-w3-1a-api-port.py`: **passed** — every internal slot-N health/wake/
  cleanliness request uses container port `9230` (host publication offset is
  not used for service-DNS calls).
- Python syntax checks: passed.

The router's internal slot API calls use the compose-network container port
`9230` for every `slot-N`. Host publishing remains `9230` for slot 1 and
`9231` for slot 2; that host-port offset is not used for `slot-N` service DNS.

A read-only router-state probe showed the following snapshot while the two pilot
browsers were reported SSO-authenticated:

- `spike-user@aikumi.pro`: active on slot 1; `/fleet/my-status` = `active`.
- `montigaud@aikumi.pro`: waiting in the human queue; `/fleet/my-status` =
  `queued`; queue position = 1.
- The router therefore had a coherent assignment for that snapshot. A reload
  showing the opposite identity or `?` is a stale/mismatched browser response
  or an identity-boundary problem, not proof that TinyAuth failed.

The probe was non-invasive: it used read-only status endpoints and did not
restart Chrome, create tabs, evict tabs, or alter queue state.

## Contract

For a request carrying one authenticated `Remote-Email`:

1. The page identity and `/queue/status` identity are the same identity.
2. An identity present in `users` receives `status: active`, `open_url`, and a
   positive or zero `session_ttl_s`; it is not represented as queue position
   `null`/`?`.
3. A waiting identity receives `status: waiting`, its stable 1-based position,
   and no running-session TTL.
4. An offered identity receives `status: offered`, `open_url`, and the offer
   countdown.
5. A backed-off identity receives explicit `status: backed_off` and
   `backoff_ttl_s`; the UI must not imply a meaningful queue position while the
   entry is intentionally hidden.
6. Reload by an already-active identity returns to that identity's own session,
   not another user's session and not a fresh landing/queue state.
7. The queue list may show other active/queued identities according to the
   configured privacy flag, but never substitutes another identity for the
   caller.
8. Missing or invalid identity must fail closed; it must never be inferred from
   a stale page, active session list, or browser storage.

## Test matrix

| ID | Scenario | Expected result | Scope |
|---|---|---|---|
| A1 | Active identity polls `/queue/status` | `active`, own `open_url`, TTL; no `?` | local + live |
| A2 | Waiting identity polls `/queue/status` | `waiting`, stable position 1, no TTL | local + live |
| A3 | Offered identity polls | `offered`, open button, offer TTL | local |
| A4 | Backed-off identity polls | explicit `backed_off`, backoff TTL, no false position | local |
| A5 | Two identities poll concurrently | each response keyed to its own header | local + live |
| A6 | Active identity reloads `/` | 302/open own session; no landing detour | local + live |
| A7 | Queue user becomes active | polling response changes to active/open state | local |
| A8 | Missing identity header | fail closed; no state transition | local + live gateway check |
| A9 | Wrong/stale identity header | cannot access another user's session | local + security |
| A10 | `/fleet/my-status` versus `/queue/status` | read-only status agrees with queue status | live |

## Acceptance evidence

- [x] Focused source regression: `test-w3-1a-queue-reconciliation.py`, 19
      checks green.
- [x] Readiness-barrier regression: `test-router-w31-readiness.py`, **2/2
      passed**.
- [x] Queue-poll readiness regression: `test-w3-1a-status-readiness.py`,
      **passed**.
- [x] Source contract regression: `test-w3-1a-source-contract.py`, **7/7
      passed**.
- [x] Existing router functional suite: `test-router.py`, **127 passed, 0
      failed**.
- [x] Live state read performed without browser mutation.
- [ ] Two-browser live matrix completed while Tigo keeps both sessions open.
- [ ] Any discrepancy captured with timestamp, request identity (not cookie),
      status JSON, and router state snapshot; no credentials, cookies, OTPs, or
      query-string password values recorded.

## Parent W3-1 recovery status (2026-08-31)

The authorized full `cb-fleet-v2` service restart used for the recreate
qualification recovered all five applications to `running:healthy`, but did not
recover an owner-bound authenticated surface. Slot-1 ended suspended and
ownerless (`cdp_ok: false`, no tabs); slot-2 was an ownerless public baseline
with `https://pmo.city/` only. The sanitized verification recorded zero exact
canonical TinyAuth cookies and no Authentik login target. This is a parent
W3-1 failure/not-proven result, not a regression verdict against the local
W3-1A readiness barrier.

Evidence artifacts: `/opt/data/w3-1-recreate-trigger-2026-08-31.json`,
`/opt/data/w3-1-recreate-monitor-2026-08-31.json`, and
`/opt/data/w3-1-recreate-verification-2026-08-31.json`.
- [x] If a product defect remains, add a failing test before changing router
      code, then deploy only after the local suite and live matrix pass.

## Operator procedure for the live matrix

Tigo keeps the two existing SSO browsers open: one as
`spike-user@aikumi.pro`, one as `montigaud@aikumi.pro`. The operator uses each
existing browser and reloads only the CloudBrowser page; do not create or close
embedded slot tabs and do not restart the fleet for this matrix.

For each browser, record only:

- header email shown;
- page state: active / queue / landing;
- displayed position or session countdown;
- whether `Open Browser` is shown;
- the corresponding read-only `/queue/status` and `/fleet/my-status` result.

A result is green only when the header, page state, and status response all
refer to the same identity. The active user's queue response should be
`active`; the waiting user's response should be `waiting` with a numeric
position. A `?` is a failure unless the response is an explicit, documented
non-position state such as `backed_off`.

## User input required

No new credential, token, or configuration is required. The two existing SSO
sessions are exactly the needed setup. The only human observation needed is to
report, for each existing browser after reloading the CloudBrowser page:

- which email is shown in the top-right header;
- whether it shows the live browser, queue, or landing page;
- whether the queue position is numeric or `?`;
- whether the two browsers remain on their respective identities.

No clicking inside the embedded CloudBrowser session is required.
