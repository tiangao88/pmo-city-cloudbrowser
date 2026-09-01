# Cloud Browser — Product Boundaries

> Version: **0.1 refactor baseline — 2026-09-01**  
> Status: **PROPOSED FOR REVIEW**  
> This document separates product responsibilities and trust boundaries. It
> does not authorize implementation, deployment, restart, credential
> rotation, or live-fleet mutation.

## 1. Product map

### 1.1 Cloud Browser

Cloud Browser provides one persistent Chromium browser per personal principal,
plus separately owned service browsers. It includes:

- browser lifecycle, slot assignment, owner binding, suspend/wake/recreate;
- profile and tab persistence, including spec-56 identity-cookie stripping;
- viewer and user input forwarding;
- router and queue behavior;
- a restricted agent-control surface;
- durable per-user downloads and their access policy.

Cloud Browser does **not** decide which Vaultwarden item to decrypt or receive
plaintext credentials.

### 1.2 Credential Broker

Credential Broker is a separate product capability with one job: execute a
validated login intent using a principal's authorized Vaultwarden material and
a broker-only browser capability, then provide a status-only result.

It owns:

- grant/session acquisition through the approved Vaultwarden interface;
- site declaration and adapter selection;
- in-memory credential use;
- form, Basic Auth, SSO, and MFA adapter execution;
- success/failure verification;
- redacted broker audit events.

It does **not** own browser lifecycle, user-facing viewer UI, Vaultwarden UI,
IdP policy, or LLM reasoning.

### 1.3 Hermes agent

Hermes is the reasoning and conversation layer. It may:

- request a broker login intent;
- drive allowed page-state operations in its owner's browser;
- receive bounded broker status;
- ask the employee for a one-time code when the policy requires it.

It may not:

- read a grant, vault key, refresh token, password, TOTP seed, or cookie value;
- select an undeclared origin;
- invoke unrestricted CDP;
- receive a credential-bearing screenshot, DOM/value dump, network body, or
  HAR through the normal API;
- override owner, profile, principal, slot, or adapter policy.

### 1.4 Router/control plane

The router is the server-side authority for authenticated request identity,
queueing, browser resolution, owner binding, and safe broker request
authorization. It may pass opaque capability references to the broker. It must
not decrypt Vaultwarden items or proxy plaintext to the agent.

A caller-provided email, slot, browser ID, or `Remote-Email` value is not an
independent authority. The router must derive or validate identity from the
authenticated control-plane context and reject mismatches.

### 1.5 GrantHub

GrantHub is the consent and revocation surface. It creates and revokes the
per-user grant described by specs 34 and 59. It must expose status, not
plaintext credentials. Its exact custody relationship with the broker must be
made consistent in the refactor: GrantHub may create/store wrapped grant
material, while only the broker may consume the credential-fetch capability at
runtime.

### 1.6 Vaultwarden

Vaultwarden remains the source-of-record for user-selected credentials. Cloud
Browser does not replace it, mirror it, or store a master password. The
employee's dedicated share-vault/collection is the consent boundary; the
implementation must not silently broaden that scope.

### 1.7 Identity provider / TinyAuth

TinyAuth and the configured IdP authenticate users to Cloud Browser, MCP, and
related PMO City surfaces. They do not define arbitrary application login
semantics. Authentik/TinyAuth is one SSO adapter input, not the generic broker
contract.

### 1.8 Viewer

The viewer renders and forwards user interaction to the owner's browser. It is
not a credential broker and must not receive Vaultwarden grant material.

### 1.9 Operator and deployment plane

Operators deploy, monitor, rotate infrastructure configuration, and respond to
incidents. Routine operator access must not include decrypted user credentials.
Host/SSH/Docker break-glass access is an administrative trust boundary and
must be audited, limited, and excluded from the normal agent threat model.

## 2. Ownership classes

| Class | Owner key | Browser visibility | Credential scope | Refresh policy |
|---|---|---|---|---|
| Personal | immutable user principal | that user and authorized agent only | that user's declared grant | user-controlled re-auth when needed |
| Service | immutable service principal | service agent/authorized ops only | that service's collection | governed automatic refresh + ops alert |
| Operator | deployment/operator identity | no personal browser by default | infrastructure only | explicit break-glass procedure |

There is no shared human browser and no shared human credential collection.
Shared infrastructure tokens may exist only as explicitly documented control
credentials; they never authorize a user identity or grant access.

## 3. Trust boundaries

### Boundary A — External client to Cloud Browser

Tinyauth/IdP authentication establishes the caller principal. The router
resolves only that principal's browser and queue state. Direct slot APIs,
profile paths, and container ports are not product interfaces.

### Boundary B — Agent to router/control plane

The agent receives a profile-scoped capability with bounded lifetime and
purpose. The router rejects altered identity, browser, slot, site, or replay
metadata. The agent never receives the broker's grant capability.

### Boundary C — Router to broker

The broker receives a server-authenticated, profile/principal/browser-bound
request. The credential-fetch capability is broker-only. The router cannot
turn a caller-selected identity into permission to decrypt another user's
items.

### Boundary D — Broker to browser

The broker uses a restricted CDP/browser capability limited to an approved tab,
origin, adapter operation, and request lifetime. The agent uses a separate
capability with no cookie/storage/network-body/password-value access.

### Boundary E — Broker to Vaultwarden/grant store

Only the broker may consume the runtime grant/session capability. Decrypted
fields exist only in broker memory for the shortest practical interval. The
legacy slot-side direct-decryption fallback is not compatible with this
boundary and must be removed or made unreachable before production.

### Boundary F — Browser profile/storage

Profile files, cookies, and app sessions are sensitive user data. The agent
gets page state through an allowlisted surface, not filesystem access. Identity
cookies are never copied across owners or restored from an archive. Durable
downloads are separate per-user data and may be exposed to the user's agent
under the FR-12 file policy.

### Boundary G — Audit/observability

Audit events are status-only and bounded. Logs, traces, screenshots, HARs,
recordings, crash dumps, and error reports are separate data classes; sensitive
artifacts require redaction, access control, and retention rules before use.

## 4. Data-flow rules

1. User consent creates a per-user grant; it never gives the agent a vault key.
2. The agent sends intent metadata, never credential material.
3. The broker resolves owner, grant, site declaration, and browser server-side.
4. The broker fills through a restricted capability.
5. The broker returns only a bounded status and safe error code.
6. The agent then acts on page state without reading credential-bearing state.
7. Revocation invalidates future reads and session minting.
8. Owner reassignment invalidates in-flight work before any fill.

## 5. Explicit non-boundaries

The following are not acceptable substitutes for a product boundary:

- a convention that the agent “will not import `vault_client.py`”;
- hiding a grant file while leaving a direct-decryption fallback in the slot;
- relying on `Remote-Email` supplied by an untrusted caller;
- relying on a page URL without application identity verification;
- returning a masked password, token length plus value, or replayable handle;
- putting credentials in a CDP URL, query string, screenshot, HAR, or exception;
- treating a healthy container, Chrome process, or viewer page as proof of
  authenticated application continuity.

## 6. Current implementation classification

| Current element | Classification | Refactor treatment |
|---|---|---|
| `sso-broker.py` Authentik watcher/filler | adapter-specific implementation | preserve behind explicit SSO adapter interface |
| `vault_client.py` grant unwrap/decrypt | sensitive broker primitive | move behind broker-only boundary; remove slot agent reachability |
| `grant-sync.py` consumption path | grant/session integration | broker-owned or explicitly split into a non-plaintext grant service |
| router owner/readiness barrier | Cloud Browser control-plane behavior | retain and bind broker requests to it |
| `pm-fill.py` / site helpers | test/prototype adapter material | convert to reviewed adapter fixtures; no ad hoc production bypass |
| `agent-browser` PoC | deterministic control/QA instrument | adopt only behind owner-aware, redacted integration |
| `NEKO_PASSWORD` and infrastructure tokens | deployment credentials | separate from user grant identity; retirement/hardening tracked |

## 7. Boundary acceptance tests

The boundary is accepted only when tests demonstrate:

- an agent can request a declared login but cannot read grant files or decrypt
  items;
- changing profile, principal, browser, slot, origin, tab, or nonce is rejected;
- the broker cannot fill an undeclared origin or a different owner's browser;
- a normal CDP/MCP session cannot read cookies, storage, network bodies,
  password values, or grant material;
- revocation blocks new use;
- reassignment cancels in-flight work;
- Authentik and ordinary form flows share the same intent contract without
  shared/static credentials;
- sensitive observability artifacts are blocked or redacted;
- operator break-glass use is distinct from the agent path and auditable.

## 8. Boundary decisions to confirm

1. Separate broker service versus broker-only sidecar.
2. Exact profile/principal/capability-token model.
3. Whether GrantHub stores wrapped material or delegates all runtime custody.
4. Agent CDP method allowlist and enforcement point.
5. Site declaration owner, review, and change process.
6. Personal versus service grant lifecycle.
7. Break-glass operator procedure and evidence retention.
