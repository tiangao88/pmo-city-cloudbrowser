# M3a: live viewer and human takeover

Status: delivery sequence approved by Tigo on 2026-09-11; implementation and
transport qualification pending. Tigo subsequently selected noVNC for M3a.
Work branch: `feat/m3-viewer-foundation`,
based on frozen M2 review target `9c113587`. No deployed runtime change.

Development progress: the disposable noVNC shared-browser spike passed display,
input and reconnect checks (see its README for evidence and limitations).
`viewer/live_connection.py` now supplies a transport-independent lifecycle
component with synthetic tests for authority checks before frame forwarding,
expiry, revocation and owner/generation changes. The disposable websockify
adapter now wires it into cookie admission, outgoing writes and idle polling;
its private x11vnc backend enforces read-only keyboard/mouse behavior. Five
loopback WebSocket tests and visible browser checks passed. The adapter is not
wired into the deployed service and its synthetic issuer is not SSO. Production
must serialize slot rebind with connection revocation, bound transport callbacks,
and qualify protocol behavior and real identity admission.
Exclusive takeover and broker/agent fencing also remain pending.

`SlotViewerAuthority` is now used by the disposable adapter with an explicitly
synthetic identity resolver. Admission uses the existing edge-identity parser
and identity-link port, requires PMOC_Users, and compares the resolved principal
with the server-owned binding. It accepts no caller-selected binding fields.
A shared process-local lock serializes admission, frame writes and rebind:
old transports close before the binding-application callback runs. Reused
generations are denied. Failed teardown blocks further transitions; failed
application leaves admission off. Synthetic concurrency tests cover this.

This is not distributed atomicity or completed SSO integration. The deployed
slot-supervisor and viewer are separate processes: the supervisor must await
viewer fencing acknowledgement before changing the browser and fail closed on
timeout/restart. Admission-time identity resolution is not continuous SSO
revocation. Trusted gateway wiring, cookie issuance, active-session expiry
propagation, display cleanup and cross-process transition qualification remain
required. Never deploy the fixture resolver as the real session issuer.

The private fencing RPC (`viewer/fence_control.py`) and optional supervisor
`viewer_fence` port now implement the disable/acknowledge half of cross-service
coordination. The client requires a fresh nonce echoed in a bounded successful
response; errors and timeouts raise before supervisor mutation. The endpoint
authenticates a dedicated service secret, closes existing connections under
the authority lock, then acknowledges. Repeated fencing while disabled is
safe; a stale request against a new binding is rejected. Loopback HTTP tests
verify close → stop → push ordering and failure paths.

This RPC is deliberately not wired into `service_runtime` or Compose yet.
The follow-up enable endpoint now requires the latest process-local fence ticket,
an explicit display-reset callback and matching browser readiness. A new fence
or viewer-process restart invalidates earlier tickets. Exact enable retries are
idempotent; different bindings cannot reuse the same completed ticket. A fresh
viewer session epoch prevents old cookies becoming valid on same-generation
resume. Cleanup/readiness failures leave admission disabled and require fencing
again. The optional supervisor enable callback runs only after startup, matching
readiness and tab restoration/cleanup.

These are tested protocol seams, not production cleanup implementation. The
display-reset callback still needs a real implementation and qualification.
The existing already-READY fast path does not silently re-enable a restarted
viewer; runtime reconciliation must explicitly obtain a fresh fence ticket.
Supervisor incarnation/lease enforcement and real SSO session issuance remain
required. All live-view-enabled deployments must make fencing mandatory;
the optional port only preserves existing viewer-less behavior during this
development stage. No image/release qualification is implied.

## Outcome

After signing in to CloudBrowser, the employee sees the same Chromium instance
Hermes controls. They can select a tab, take exclusive keyboard/mouse control,
sign in manually when supported, and explicitly return control. A second,
unrelated browser inside an iframe does not meet this requirement.

Full sequence: review/fixes → M2a browser control → M3a viewer/takeover → M2b
application login → M3b self-service consent. The outstanding security scan
remains unfinished; do not restart it through a different path to work around
the platform block. No credential tests or rollout until the gate is resolved.

## Feasibility assessment

Current `services/browser/Dockerfile` launches headless Chromium. Its process
and owner-specific profile are managed by `BrowserProcess`; the viewer bridge
only returns a stream descriptor, not video or input. Therefore an iframe alone
cannot enable the required product behavior.

noVNC is the selected transport direction: WebSockets through the authenticated
HTTPS gateway, with a private VNC backend and the same headed Chromium instance.
No STUN/TURN service is required for that transport. Resource savings versus
Neko remain unmeasured. The [disposable harness](../experiments/novnc/README.md)
is a feasibility experiment, not an authenticated deployment. See
[ADR-0006](../specs/adr/0006-novnc-viewer-direction.md).

Neko remains a comparison reference, not the selected integration. Its
[installation documentation](https://neko.m1k1o.net/docs/v3/installation)
describes a Docker/WebRTC deployment. The
[authentication documentation](https://neko.m1k1o.net/docs/v3/configuration/authentication)
separates watching, controlling and clipboard permissions; these must be tied
to CloudBrowser ownership rather than granting shared-room access.
[Reverse-proxy setup](https://neko.m1k1o.net/docs/v3/reverse-proxy-setup) and
[UI customization](https://neko.m1k1o.net/docs/v3/customization/ui) are integration
references, not proof of deployed behavior. Sources checked 2026-09-11.

Historical Neko experiments under `specs/archive/` are reference only. Do not
copy their browser version, exposed CDP relay, shared credentials, extensions
or profile volumes into this implementation.

## Ordered work packages

1. **Disposable same-browser spike.** Use synthetic accounts/pages, new scratch
   storage and no production secrets or profile mounts. Prove headed Chromium
   renders through noVNC and remains controlled by the existing mediated API. Preserve
   exactly one process owner: no competing automatic browser launcher. Record
   image digest, browser version, display ownership, process UID, launch/stop
   behavior, resource usage and video/input connectivity. Do not modify dev01
   ports, firewall or existing containers for this experiment.
2. **Transport decision.** Record an ADR after evidence, covering lifecycle,
   deployment network requirements, authentication, session revocation, input
   arbitration, rollback and release/image-count effects. If noVNC cannot satisfy
   the boundaries without a broad rewrite, document the failed criterion before
   evaluating a fallback. No current-version or security-qualification claim is
   implied by using the v3 documentation.
3. **Owner-bound live view.** Route only the assigned active browser, initially
   read-only. Authenticate signaling and stream admission; invalidate existing
   connections on owner/generation change, not just new page loads. No public
   room, reusable shared password or browser/backend endpoint in MCP results.
4. **Exclusive takeover.** Add server-enforced control state and fencing, then
   keyboard/mouse input. Do not rely on the viewer's visual control indicator to stop
   Hermes: the mediated action path must obey the same control owner.
5. **Qualification and staged rollout.** Pass the matrix below, resolve review
   gates, qualify immutable images and clean installation/rollback, then deploy
   with explicit environment approval. Only then invite employee testing.

## Proposed control behavior (contract to implement)

| State/event | Required behavior |
| --- | --- |
| Agent mode | Employee may observe; human keyboard/mouse disabled. |
| Takeover requested | Stop admitting agent operations and broker login; drain or cancel in-flight work safely before acknowledging human control. Unknown in-flight login outcomes must not be retried automatically. |
| Human mode | Human input allowed; agent reads, screenshots, input and broker login rejected. Do not record keystrokes or mirror clipboard into agent output. |
| Human disconnect | Input disabled; remain paused. Never silently resume Hermes. |
| Reconnect | Reauthorize current owner/generation; no replay of buffered input. |
| Explicit resume | End human input, release held keys/buttons, issue fresh fenced agent authority. Resume only after all relevant checks succeed. |
| Leave, expiry, rebind or service restart | Revoke stream/input authority; no last frame, queued event or prior connection delivered to the next owner. |

This is a proposed contract, not an implemented security guarantee. Clipboard,
file upload, recording, microphone/camera and remote desktop administration stay
out of the minimum increment. CloudFiles remains the download path. Login pages
and user secrets must not become agent-visible merely because the viewer exists.

## Exit tests

| Test | Evidence required |
| --- | --- |
| Same browser | Hermes opens a synthetic page; employee sees that exact tab and a shared state change. |
| Control exclusion | Concurrent agent actions and takeover requests cannot produce agent input or observation after acknowledged human control. |
| Owner isolation | A → B → A allocation rejects old streams and delayed input and never displays another owner's frame. |
| Reconnect/restart | Disconnect stays paused; explicit resume works; stale credentials/epochs fail closed. |
| Human input | Typing, tab selection, mouse clicks, held-key release and supported keyboard layout work on a disposable page. |
| Network/deployment | Video and input work through intended proxy/network paths; clean install does not depend on undeclared environment injection. |
| Secret boundary | No input values, video, clipboard, session secrets or backend control endpoints appear in agent responses, logs or test artifacts. Use synthetic canaries only. |

## When Tigo is needed

No credentials or SSO testing now. Once review gates and M3a synthetic tests pass:

1. Open the deployed viewer and confirm that the page Hermes opened is visible.
2. Take control, interact with a harmless page, disconnect/reconnect, then resume.
3. For M2b, choose a non-production Basic/Authentik application and authorized
   test account. Enter any human secrets only into the authenticated viewer, not
   chat. Broker-driven login separately requires approved consent provisioning
   and account proof; a successful manual login is not a substitute.
