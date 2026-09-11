# Desktop candidate — not release-qualified

The opt-in `cloudbrowser.viewer.desktop_runtime` co-locates the existing browser
service, Xvfb, x11vnc, noVNC transport and viewer authority. One shared lock
serializes browser responses, stream forwarding, lifecycle and control changes.
The router, identity-link and slot supervisor remain separate services.
No release Compose, CI publication matrix or dev01 deployment selects this image.
The separate [candidate Compose stack](../../deploy/desktop/compose.candidate.yaml)
now wires these services together. The desktop entrypoint runs Python 3.12;
websockify is installed for that interpreter rather than borrowed from Debian's
system Python. This remains a candidate, not a supported release image.

## Configuration boundary

- Set `CB_EXPERIMENTAL_DESKTOP=1`, `CB_EDGE_AUTH=traefik-forwardauth`, an exact
  `CB_VIEWER_PUBLIC_ORIGIN=https://...`, distinct 32-character-or-longer
  `CB_VIEWER_TOKEN_SECRET` and `CB_VIEWER_CONTROL_SECRET`, and the existing
  identity-link and router environment. Never reuse the fixture secrets.
- Keep `CB_BROWSER_AUTOSTART=0`; the supervisor assigns a binding before start.
  Chromium must be headed. The image owns its private `:99` display.
- Only port 8082 may reach the authenticated, header-sanitizing edge. Ports
  9230 and 6083 are private control-plane endpoints; 5900, 9222 and 6081 remain
  loopback-only. Do not publish control/CDP/VNC to a host or agent network.
- Configure the supervisor's existing experimental viewer-control client with
  its dedicated secret and private URL. Its renewal worker never re-enables an
  expired/restarted authority; a fresh fence/enable lifecycle is required.
  Explicit wake now repairs expired viewer authority even when Chromium remains
  ready. A successful retry only renews, preserving human/paused control mode.
- Preserve owner-partitioned profile storage. Each start gets a fresh X server,
  not a fresh user profile. Confirm old process termination before replacement.
- Credential UI forwarding is disabled and broker submit configuration is
  rejected at candidate startup. **The upstream router/broker must also have
  credential forwarding disabled.** This image cannot prevent an independently
  configured upstream service from retrieving credentials.

## Control semantics

Newly enabled slots are agent-controlled with a read-only desktop. Takeover
drains browser operations holding the shared lock, revokes old streams, resets
VNC input and admits one controlling stream. Requests received before a mode
change cannot execute after resume. Human disconnect leaves the agent paused;
explicit resume releases pressed keys/buttons and restores read-only viewing.
Failed reset/teardown leaves admission unavailable. Agent/broker page operations
are blocked while paused. An opt-in cross-process whole-job guard now also
blocks upstream credential fetching; see [its contract and limitations](../../docs/M3-BROKER-JOB-COORDINATION.md).
It is exercised with synthetic jobs only. Busy takeover/resume stays paused and
requires an explicit retry after the job exits; timeout alone does not unlock it.

## Reproducible local checks

Build from the repository root:

```sh
docker build -f services/desktop/Dockerfile -t cloudbrowser-desktop:candidate-local .
docker build -f experiments/novnc/Dockerfile.tests -t cloudbrowser-desktop:tests-local .
docker run --rm --network none cloudbrowser-desktop:tests-local
```

Run `/fixture/candidate_smoke.py` as the candidate container entrypoint, with
`experiments/novnc` mounted read-only at `/fixture`. No network or published
ports are needed. This exercises real Chromium, the actual candidate process,
a synthetic identity-link HTTP service, HTTPS cookies and WSS. It checks A/B/A
cookie continuity, full process restart, stale authority, takeover, disconnect,
held Shift/button release and explicit resume. It never uses real credentials.
It also uses the real supervisor over the private HTTP interfaces, keeps an old
WSS transport open across owner changes, and decodes the first raw framebuffer
after each new admission. A/B/A and restart samples each contained 870,708
owner-canary pixels and zero other-owner-canary pixels. Xvfb, Chromium and x11vnc
are separately killed inside the disposable container: old streams close, old
cookies fail, and supervisor recovery produces a clean first framebuffer.
These finite canary checks are evidence, not proof against every pixel leak.
One forced-crash run logged a disconnected health client's `BrokenPipeError`;
the isolated request handler ended and the recovery assertions still passed.
That diagnostic noise is not counted as a failed isolation assertion or hidden
as a clean-log qualification.
`CB_SMOKE_SERVE=1` keeps the last synthetic binding renewed for localhost visual
QA; expose **only** `127.0.0.1:16080:6080` for that disposable fixture.

For the real service topology, follow [the standalone stack instructions](../../deploy/desktop/README.md).
`stack_smoke.py` passed through actual Traefik, desktop, router, supervisor,
agent-control and identity-link services with only the external authentication
response replaced by a synthetic fixture. It covers WSS framebuffer delivery,
anonymous denial, caller identity-header replacement, activation, renewal beyond
the 15-second lease, takeover/resume, disabled broker forwarding and A/B/A.

Integration uncovered and fixed three lifecycle issues: headed cleanup closed
the last blank tab; fencing blocked the supervisor's URL snapshot; an already-
ready wake could not repair an expired viewer lease. Private `/browser/pages`
remains available for supervisor snapshots, while `/agent/*` stays paused.

## Qualification / rollback gates

Build success is not a deployment GO. Remaining gates include real SSO session
and revocation testing, broader failure/leader-fencing coverage, whole-job broker
fencing deployment qualification, dependency/SBOM review, immutable image publication and installation/rollback.
The image uses mutable Debian packages and Chromium `--no-sandbox`; those are
explicit unqualified constraints, not approved production settings.

No deployment changed, so no production rollback is necessary. Before any future
rollout: record existing image digests and configuration, back up profile/state
volumes, drain active users, and rehearse restoring the prior runtime on copies.
Do not overwrite production volumes or publish this candidate merely to test
rollback. The outstanding blocked review described in the M3 plan remains a NO-GO.
