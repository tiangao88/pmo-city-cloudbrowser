# ADR-0006: noVNC-first human viewer

- Date: 2026-09-11
- Status: User-approved direction; prototype/integration qualification pending

## Decision

Reuse noVNC for M3a human viewing and input. Preserve the existing Chromium
lifecycle and owner-profile model; add a headed display and private VNC backend.
Expose only authenticated HTTPS/WebSocket gateway routes in a future deployment.
Do not expose raw VNC/CDP, use shared-room credentials, or launch an unrelated
browser behind the UI. Client-side viewOnly is not a takeover enforcement gate.

## Rationale and limits

The user reports prior Neko resource overhead and potential TURN requirements.
noVNC uses WebSockets, avoiding WebRTC ICE/STUN/TURN operational requirements.
Its actual CPU/RAM/bandwidth cost must be measured on representative pages; no
lower-resource claim is established by this decision. Audio/video conferencing
is not the acceptance target for this minimum milestone.

References: [noVNC architecture](https://novnc.com/noVNC/),
[embedding](https://novnc.com/noVNC/docs/EMBEDDING.html),
[RFB API](https://novnc.com/noVNC/docs/API.html), checked 2026-09-11.

## Vaultwarden and agent separation

Vaultwarden is the user's credential source of record. The user explicitly
authorizes selected credentials; only the deterministic broker may consume the
automated vault-access grant and use it for a declared login. The intended
application necessarily receives its login credential through the broker-only
browser path; no credential may be returned to Hermes.

Hermes must neither browse the vault UI nor reach vault APIs, grant files or an
unlocked vault extension through alternate tools. This must be enforced across
the actual Hermes execution environment, not merely described in an MCP prompt.
Do not import the old unlocked-extension/direct-CDP integration. noVNC is for
the authenticated human, never an additional agent observation/control tool.
Human takeover suspends agent observation/input and broker login before human
input is enabled. Clipboard and recording remain outside M3a.

## Qualification

Start with experiments/novnc using synthetic data and disposable profiles only.
Then implement authenticated stream admission, lifecycle revocation, server-side
takeover fencing, reconnect and owner-switch tests. The blocked security review
must be resolved before integration release, credentials, merge or rollout.
See [M3a acceptance matrix](../../docs/M3-VIEWER-FOUNDATION.md).
