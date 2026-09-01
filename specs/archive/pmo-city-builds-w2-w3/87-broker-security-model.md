# Cloud Browser — Credential Broker Security Model

> Version: **0.1 refactor baseline — 2026-09-01**  
> Status: **PROPOSED FOR REVIEW**  
> This is the security contract for the credential-broker refactor. It records
> the observed bypass and the controls that must be implemented and tested. It
> does not authorize implementation or deployment.

## 1. Security objective

A Hermes agent may ask the broker to log the current principal into a declared
site. The agent must not be able to obtain or replay the material used to do
that, even through normal browser-control APIs, files, logs, screenshots,
network capture, or altered request metadata.

The security boundary is therefore not “the agent promises not to call a
helper.” It is an enforced capability separation:

```text
Hermes profile agent
        │ intent-only, profile-bound capability
        ▼
router / broker authorization
        │ broker-only grant capability
        ▼
Credential Broker ── restricted fill capability ──> owner's Chromium tab
        │
        └── Vaultwarden/grant session (plaintext only in broker memory)
```

## 2. Threat model

### In scope

- a model or agent attempting to read a grant file or import credential code;
- a compromised or over-permissioned browser-control client;
- altered owner, profile, slot, browser, tab, origin, adapter, or nonce fields;
- stale requests after slot reassignment;
- cross-user grant selection;
- shared/static legacy SSO credentials;
- credential leakage through logs, exceptions, screenshots, HARs, traces, or
  network capture;
- revocation races and refresh-token rotation;
- incorrect success claims for a wrong or unauthenticated account.

### Out of scope but separately controlled

- a fully compromised host root account;
- compromise of the underlying IdP or Vaultwarden itself;
- endpoint malware on the employee's own device;
- business-site compromise.

Host break-glass access remains an administrative trust boundary. It is not a
normal agent capability and requires separate controls and audit.

## 3. Security invariants

### S1 — No agent credential capability

The agent process/container has no filesystem, environment variable, socket,
API route, Python module, or network path that can unwrap a grant, mint a
Vaultwarden session, decrypt an item, or read broker plaintext.

The slot-side `vault_client.py` direct-decryption path and any fallback to a
local grant directory violate S1. They must be removed, isolated, or made
unreachable before production acceptance.

### S2 — Broker-only grant custody

Only the broker can consume the runtime grant/session capability. Router,
viewer, agent, normal slot runtime, and audit sink receive opaque references or
status only. Grant material is per principal and revocable.

### S3 — Server-derived binding

The router derives the authenticated Hermes profile and principal. The broker
revalidates profile, principal, browser, slot, tab, site declaration, and
request generation immediately before fetch and before fill. Caller-provided
identity is an assertion to validate, not authority to trust.

### S4 — Exact destination authorization

Credential use is permitted only for a versioned site declaration and exact
origin/redirect policy. A display name, arbitrary URL, selector, or agent text
cannot expand the destination.

### S5 — Restricted browser access

Agent and broker browser capabilities are separate. Agent operations cannot
read cookies, storage, network bodies, password input values, authorization
headers, or unrestricted runtime state. Broker fill operations are scoped to a
validated tab/origin and expire with the request.

### S6 — No secret observability

Credential material must not appear in stdout, logs, audit, model context,
router state, exception strings, crash dumps, screenshots, recordings, traces,
HARs, or test reports. Sensitive artifacts are disabled by default or redacted
before retention/sharing.

### S7 — Revocation and reassignment win

Revocation, owner change, slot reassignment, browser destruction, request
expiry, or policy change invalidates in-flight work. No fill happens after the
binding becomes stale.

### S8 — No false success

The broker returns authenticated only after application-side success and
requested-account verification. Infrastructure health, IdP success, a changed
URL, or a non-login-looking page alone is insufficient.

## 4. Required capability design

### 4.1 Agent capability

The agent capability is a short-lived, audience-bound authorization for an
intent. It contains no grant, vault, bearer, refresh, cookie, or decryption
secret. At minimum it must bind:

- `profile_id`;
- immutable `principal_id`;
- deployment/tenant identifier;
- broker audience and operation (`credential.login`);
- declared `site_id` and adapter version;
- browser/session binding or server-resolved browser reference;
- issued-at, expiry, nonce, and one-time/replay state.

The agent cannot choose a different principal by placing another email in the
payload. The router must derive that field from authenticated context.

### 4.2 Broker capability

The broker capability is not handed to the agent. It is minted or resolved by
the router/broker authorization path for one request, principal, site, tab, and
short lifetime. It permits only the minimum grant fetch, adapter steps, and
verification needed for that request.

### 4.3 Browser capability

A browser capability exposes safe page-state operations to the agent and a
separate fill/verification operation to the broker. The implementation must
avoid giving the agent a general `Runtime.evaluate` or raw CDP WebSocket that
can bypass the allowlist.

## 5. Required process and deployment separation

The preferred production shape is a separately isolated broker service. A
broker-only sidecar is acceptable only if all of these are true:

- the agent process cannot access its filesystem, Unix socket, PID, environment,
  imports, or local grant path;
- the broker capability endpoint authenticates the router and validates scope;
- the browser receives a restricted broker channel, not a shared unrestricted
  CDP socket;
- the grant store is not mounted into agent/slot containers;
- a compromised agent cannot ask the broker to return decrypted data;
- container user, Linux capabilities, seccomp/AppArmor, network policy, and
  read-only mounts are tested rather than assumed.

The current in-slot direct-helper pattern is prohibited in production.

## 6. Login adapter security contract

Every adapter must implement the same bounded lifecycle:

1. validate intent, principal, site declaration, and browser binding;
2. acquire the minimum credential fields in broker memory;
3. establish or attach to the declared target tab;
4. verify current origin and adapter preconditions;
5. perform deterministic fill/challenge steps;
6. erase temporary references as practical;
7. verify application identity and success;
8. emit status-only audit and discard the operation capability.

### Form adapter

- selectors and field roles come from reviewed site metadata, not arbitrary
  agent input;
- no credential values are returned by evaluate/readback;
- multi-step, iframe, and shadow-DOM behavior is explicit per adapter;
- ambiguous or unexpected forms fail closed.

### HTTP Basic adapter

- use CDP/browser challenge handling, never URL credentials;
- require HTTPS and exact-origin declaration;
- do not forward credentials across undeclared redirects;
- stop on challenge loops and origin changes.

### SSO adapter

- Authentik/TinyAuth is an explicit adapter;
- callback and popup origins are declared;
- IdP identity and application identity are both checked;
- stale cookies are not copied across owners;
- an IdP success page is not application success.

### MFA adapter

- TOTP seed is broker-only and used only for the declared flow;
- no seed means one-shot human code handoff;
- push/SMS/email/WebAuthn/passkey/security-key/CAPTCHA/recovery are explicit
  unsupported or human-handoff outcomes until separately implemented;
- no guesses, brute force, silent downgrade, or code logging.

## 7. Agent/CDP denylist

The normal agent surface must deny or mediate:

- `Network.getAllCookies`, cookie mutation, and cookie-value reads;
- browser storage and IndexedDB reads containing session/credential data;
- network interception, request/response bodies, authorization headers, and HAR;
- password input value reads or screenshots while sensitive fields are present;
- unrestricted `Runtime.evaluate`, `Runtime.getProperties`, and filesystem APIs;
- raw CDP socket access and port discovery;
- grant-store paths, broker environment, process inspection, and container exec;
- navigation/fill to undeclared credential origins;
- arbitrary target creation when it can escape the owner/tab policy.

Allowed page-state extraction must be bounded and tested against secret-bearing
fixtures. The policy may redact or reject a page rather than attempt perfect
secret detection.

## 8. Attack-case acceptance matrix

| Case | Required result |
|---|---|
| Agent imports `vault_client` | module/path unavailable; no credential capability |
| Agent reads grant directory | denied/not mounted; no user material |
| Agent alters `principal_id` | `owner_mismatch` / authorization failure |
| Agent alters `profile_id` | audience/binding failure |
| Agent alters slot/browser/tab | binding failure |
| Agent changes target origin | `invalid_target` |
| Agent replays nonce | replay rejection |
| Slot owner changes mid-request | cancel before fetch/fill |
| Grant revoked mid-request | no new fetch/mint/fill |
| Shared static SSO file exists | startup/release check fails; broker refuses to run |
| Form has ambiguous fields | `unsupported` with no fill |
| HTTP Basic redirects elsewhere | no credential forwarding |
| Authentik succeeds but app identity is wrong | `success_unverified` or failure |
| TOTP missing | one-time human handoff, never guessed |
| Unsupported MFA appears | explicit handoff/unsupported, no bypass |
| Debug/logging enabled | secret scan fails the build/release |
| Screenshot/HAR/trace captures a password | artifact blocked or redacted; no retention |
| Agent requests unrestricted CDP | denied and audited as safe status |

## 9. Logging and evidence rules

Use the `cloudbrowser.audit.v1` envelope from spec 82 with bounded event types
and error codes. Safe events include request accepted/rejected, adapter type,
principal classification, owner-match boolean, outcome, and duration. Never
include raw URLs with credentials, headers, DOM, page text, filenames revealing
secrets, exception strings, or values merely masked with `***`.

Security tests must scan:

- broker stdout/stderr;
- router and container logs;
- audit records;
- agent tool responses and conversation fixtures;
- crash/trace/HAR/screenshot/recording outputs;
- temporary files and environment snapshots.

## 10. Migration controls

During migration:

1. run old Authentik adapter and new broker behind distinct explicit routes;
2. prohibit fallback from new requests to legacy slot-side decryption;
3. dual-run only with synthetic/controlled test credentials, never live users;
4. compare status-only results and audit events;
5. disable legacy direct paths before production acceptance;
6. retain a rollback that restores code/config without restoring shared/static
   credentials or identity cookies.

Migration is not complete while the agent can reach the legacy helper or while
an old shared credential file can be loaded after restart.

## 11. Open security decisions

- separate service versus sidecar;
- capability-token issuer, claims, audience, nonce, and replay store;
- exact CDP mediation layer and denylist enforcement;
- process/container hardening profile;
- whether broker plaintext may ever enter a browser page value (required for
  login, but not exposed through agent reads);
- sensitive artifact redaction implementation and retention;
- break-glass operator controls and incident response;
- formal threat model review before production.
