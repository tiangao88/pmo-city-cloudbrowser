# Cloud Browser — Credential Broker PRD

> Version: **0.1 refactor baseline — 2026-09-01**  
> Status: **PROPOSED FOR REVIEW — no implementation or deployment authorized by
> this document**  
> Supersedes the implicit assumption that the deployed Authentik broker is the
> complete FR-9 product. Existing W2/D15 behavior remains a compatibility
> adapter until the refactor is agreed.

## 1. Executive decision

Cloud Browser consists of two related but separate products:

1. **Cloud Browser runtime** — a persistent, owner-bound Chromium browser,
   viewer, routing/lifecycle controls, and safe agent-control surface.
2. **Credential Broker** — a deterministic, non-LLM service that accepts a
   narrowly scoped login intent, obtains an explicitly authorized credential
   from the user's Vaultwarden grant, fills the user's browser, and returns a
   status-only result.

The broker is not the browser runtime, not the viewer, not Vaultwarden, not an
identity provider, and not an agent. Authentik/TinyAuth login is one broker
adapter, not the broker's product boundary.

## 2. Problem and user value

A Hermes agent must be able to act in a user's cloud browser without receiving
the user's passwords, tokens, OTP seeds, or one-time codes. The user grants
access to selected Vaultwarden material once. Thereafter the broker performs
the mechanical login while the agent sees only page state and a bounded result.

The product must support real websites encountered by PMO City users, including
ordinary username/password forms, HTTP Basic Auth, SSO redirects, and the
specified MFA handoff modes. Unsupported or ambiguous login flows must fail
closed and become an explicit human handoff; they must not be guessed by an
LLM or a permissive fallback.

## 3. Goals

### G1 — Zero credential exposure to the agent

Plaintext usernames, passwords, refresh tokens, access tokens, cookie values,
TOTP seeds, and OTP codes must not be returned by the broker API, inserted into
agent context, written to agent-visible logs, or exposed through the normal
agent browser-control API.

### G2 — Generic declared-site login

After a valid grant, `credential.login` must support a declared site through a
versioned adapter contract. The first adapters are:

- ordinary username/password form;
- HTTP Basic Auth challenge;
- OIDC/SSO redirect flow;
- TOTP at an application or IdP MFA stage;
- human one-time-code handoff when no stored TOTP seed exists.

“Generic” means adapter-driven and policy-bound. It does not mean arbitrary
JavaScript, unrestricted navigation, or an LLM deciding where to send secrets.

### G3 — Owner and profile correctness

Every login request is bound server-side to exactly one Hermes profile, one
principal, and one browser owner. The caller cannot select another user by
changing an email, slot, browser ID, or URL parameter.

### G4 — Deterministic operation

The broker performs a fixed sequence selected by validated site metadata and
login type. It does not contain an LLM and does not delegate credential-bearing
decisions to the agent.

### G5 — Revocable per-user access

The existing two-leg grant model remains: a wrapped vault key plus a wrapped
Vaultwarden refresh-token/session leg. Revocation must stop new item reads and
new session minting. Existing short-lived broker sessions expire within their
defined lifetime.

### G6 — Recoverable authenticated surfaces

A recovered browser must be able to use the same broker contract to reach an
owner-bound authenticated application surface. Recovery must never restore an
identity cookie from another user or silently use a shared/static credential.

## 4. Non-goals

- Building or replacing Vaultwarden or an identity provider.
- Storing master passwords.
- Returning credentials to agents, users through the agent API, or operators.
- Making the broker a general remote desktop, proxy, or web automation agent.
- Letting an LLM choose arbitrary credential destinations or bypass site policy.
- Supporting every MFA mechanism in the first refactor.
- Treating an authenticated URL alone as proof of successful login.
- Making personal browsers shared team browsers.
- Adopting agent-browser in production without its own owner-aware and
  sensitive-artifact controls.

## 5. Personas and actors

| Actor | Responsibility | Credential access |
|---|---|---|
| Employee | grants selected vault items; may complete human MFA | sees their own browser; may type directly |
| Hermes agent | requests intent; drives page-state tools; asks for a code when required | no Vaultwarden grant or plaintext credential access |
| Credential Broker | resolves policy, reads Vaultwarden through its capability, fills and verifies | only runtime plaintext holder |
| Cloud Browser runtime | owns browser lifecycle and restricted CDP bridge | no grant-decryption capability |
| Router/control plane | authenticates and authorizes requests; resolves owner/slot | no plaintext credential access |
| GrantHub | creates/revokes per-user grant material according to its contract | handles grant material only as explicitly designed |
| Vaultwarden | stores user-selected items | source of credential material |
| Operator | deploys, monitors, and responds to incidents | no routine plaintext access |
| Service agent | drives a service-owned browser with its own principal/collection | isolated service grant, never a personal grant |

The table is a product boundary, not a claim that the current deployment fully
enforces every separation. Enforcement is an acceptance criterion below.

## 6. User journeys

### 6.1 One-time grant

1. The employee opens the existing Secrets/GrantHub flow.
2. The employee authenticates and grants the selected Vaultwarden scope.
3. GrantHub stores per-user wrapped material and exposes status only.
4. The broker can later mint a short-lived Vaultwarden session without asking
   the employee to unlock again, until revocation.

### 6.2 Agent-requested login

1. The agent calls the intent-only broker operation for the current owner:
   `credential.login(site, username, target)`.
2. The broker derives the principal, browser, grant, and permitted site from
   authenticated server-side context.
3. The broker selects a versioned adapter and validates the target origin.
4. The broker fetches and decrypts the minimum required fields in memory.
5. The broker fills through a restricted browser capability and verifies the
   application identity/success marker.
6. The agent receives a bounded status such as `authenticated`, `mfa_required`,
   `failed`, `not_shared`, or `unsupported` plus a safe error code.

### 6.3 Human MFA handoff

If no TOTP seed is present, the broker pauses at a code-request state. The agent
asks the employee for the one-time code. The code is submitted through a
one-shot, broker-scoped endpoint and is never returned to the agent, logged, or
stored. The broker verifies the result and invalidates the code request.

### 6.4 Recovery

After wake/restart/recreate, identity cookies are stripped as required by
spec-56. The broker re-authenticates only the current owner through a declared
adapter. The recovery result must include owner match and application success
proof; infrastructure health alone is insufficient.

## 7. Functional requirements

### PRD-BR-01 — Intent-only request

The broker API accepts only a validated intent. Minimum logical fields:

- `request_id` — opaque, server-generated or nonce-bound;
- `profile_id` — authenticated Hermes profile context, not caller-selected;
- `principal_id` — immutable user or service principal, server-derived;
- `browser_id` — server-resolved current browser;
- `site_id` or exact declared origin;
- `username_ref` or account selector, never a password;
- optional `target_tab_id`, constrained to the owner's browser;
- optional idempotency key.

The public agent response contains status, safe error code, and bounded timing;
never credentials, tokens, cookie values, DOM values, network bodies, or raw
exception text.

### PRD-BR-02 — Site declaration and allowlist

A site declaration is versioned, immutable for a request, and tied to the
principal's grant. It specifies:

- exact origin and allowed redirect origins;
- login type and adapter version;
- permitted path or login entry point;
- field roles or deterministic selectors where needed;
- success and failure assertions;
- MFA policy;
- maximum duration and retry policy;
- whether human handoff is allowed.

Host matching must be exact by default. Subdomains, redirects, and wildcards
require explicit declarations. A vault item's display name is never sufficient
authorization.

### PRD-BR-03 — Form-login adapter

The adapter supports documented multi-step username/password forms, including
iframes and shadow DOM only through bounded, site-declared selectors or a
reviewed adapter. It must:

- never use arbitrary agent-provided selectors for credential fields;
- submit username and password in the declared order;
- avoid duplicate submission and lockout loops;
- clear transient references after use where the browser permits;
- verify both successful authentication and requested account identity;
- return `unsupported` or `failed` on ambiguity.

### PRD-BR-04 — HTTP Basic adapter

The adapter handles a browser HTTP-auth challenge without placing credentials
in a URL, page text, logs, or agent-visible response. Credentials are scoped to
the exact declared origin and request lifetime. Redirects to another origin
must not receive the credential unless separately declared. Challenge loops,
non-HTTPS targets, and ambiguous origin matches fail closed.

### PRD-BR-05 — SSO adapter

The SSO adapter supports declared OIDC/SAML/IdP flows through an adapter
contract. Authentik/TinyAuth is the first existing implementation. The generic
contract must define login origin, callback origins, popup/window behavior,
account-selection policy, MFA stages, and application-side success proof. An IdP
success page without application authentication is not sufficient.

### PRD-BR-06 — MFA policy

The first release supports:

- stored TOTP seed → broker computes and submits the code;
- no stored seed → one-time human code request;
- unsupported push, SMS, email-link, WebAuthn/passkey, security-key, CAPTCHA,
  and recovery flows → explicit human handoff or `unsupported`.

The broker must never guess, brute-force, or silently downgrade MFA.

### PRD-BR-07 — Success verification

Each adapter declares a success assertion. It must establish:

1. the target application is no longer at its login state;
2. the browser is on an allowed origin/path;
3. the authenticated account equals the requested principal/account where the
   application exposes that identity;
4. no duplicate or wrong-owner session is accepted.

Evidence is a bounded boolean/status result and redacted audit event, not page
content.

### PRD-BR-08 — Failure and retry behavior

Failures use a bounded taxonomy: `not_shared`, `revoked`, `owner_mismatch`,
`unsupported`, `invalid_target`, `mfa_required`, `credential_rejected`,
`success_unverified`, `timeout`, `browser_unavailable`, and `internal`. No
unbounded silent retries. Credential rejection pauses the task and asks the
employee to update the vault entry. Repeated challenge/lockout signals stop the
adapter.

### PRD-BR-09 — Owner-safe recovery

The broker must re-resolve the current owner immediately before credential
fetch and immediately before fill. Any owner, profile, browser, slot, or
principal change invalidates the operation. A slot reassignment cancels in-flight
work. A stale request cannot resume against a new owner.

### PRD-BR-10 — Grant and session lifecycle

The broker uses the per-user grant and two-leg session model documented in
specs 34 and 59. Grant revocation, failed refresh, and owner change invalidate
broker capabilities. Personal-browser session expiry remains distinct from
browser idle suspension; service principals have a separately governed refresh
policy.

### PRD-BR-11 — Restricted browser capability

Credential filling must use a broker-only browser capability. The normal agent
surface must not expose unrestricted CDP methods capable of reading cookies,
storage, network bodies, password values, or arbitrary runtime state. The
broker capability is scoped to the current tab/origin and expires with the
request.

### PRD-BR-12 — Audit

Emit status-only structured events for request accepted/rejected, adapter
selected, MFA requested/completed, fill attempted, success/failure, revocation,
and owner mismatch. Apply `cloudbrowser.audit.v1`, bounded error codes, opaque
request IDs, and the prohibition list in spec 82. Never record credentials,
secrets, headers, page content, screenshots, HARs, DOM, network bodies, or raw
exception strings.

## 8. Acceptance criteria

The refactor is not complete until all are demonstrated:

- [ ] A real ordinary login item (Unlatch or equivalent) succeeds through the
      broker API, with no direct vault-client helper available to the agent.
- [ ] The existing Authentik/TinyAuth flow works as an adapter and cannot use
      another principal's material.
- [ ] HTTP Basic Auth succeeds on a controlled test origin with exact-origin
      scoping and no credential-bearing URL.
- [ ] SSO success is followed by application identity verification.
- [ ] TOTP and no-seed human handoff are both tested; unsupported MFA fails
      closed.
- [ ] Revocation stops new fetches/session minting and is reflected in status.
- [ ] Agent API fuzzing cannot read grant files, decrypted fields, cookies,
      storage, network bodies, password input values, or unrestricted CDP
      state.
- [ ] Requests with altered profile, owner, slot, browser, target origin, or
      replayed nonce fail closed.
- [ ] Browser recovery proves owner-bound authenticated application continuity
      through the broker after `/restart`, idle wake, and full recreate.
- [ ] Audit/log/model-context scans find no prohibited credential-bearing data.
- [ ] A migration test proves old Authentik behavior and new adapter behavior
      can coexist during rollout without a cross-user fallback.

## 9. Compatibility and migration principles

The current Authentik/TinyAuth broker remains available only as an explicit
adapter during migration. It must not silently become a generic fallback. The
legacy direct-store path and slot-side credential-decryption helper are
migration blockers and must be removed or made unreachable before production
acceptance.

Existing personal browser profiles, tab snapshots, per-user archives, and
spec-56 cookie stripping remain compatible. The refactor changes the credential
and control boundary, not the user's browser ownership model.

## 10. Decisions still required before implementation

These are product decisions, not implementation details:

1. Separate broker service versus broker process with a broker-only sidecar;
2. exact Hermes profile identity and capability-token format;
3. restricted CDP method allowlist and enforcement point;
4. site-declaration storage and review/update process;
5. first adapter scope beyond Authentik and Unlatch;
6. whether user-supplied MFA codes may transit the router and exact TTL;
7. audit sink and sensitive-artifact policy for screenshots/HAR/recordings;
8. migration and rollback strategy, including legacy broker disablement;
9. revised W3/W4 schedule after the security boundary is baselined.
