# Experimental whole-job broker coordination

Status: implemented for synthetic qualification, **not enabled for real
credentials or in dev01**. The separate desktop Compose stack still has no
broker and disables credential forwarding. The outstanding security-review
block remains unchanged; these functional checks do not replace that review.

## Contract

`CB_EXPERIMENTAL_BROKER_JOBS_DIR` opts the desktop authority and broker runtime
into a shared, per-slot local-filesystem guard. Both must refer to the **same
directory/inodes**. The broker remains a separate process; the guard contains
only an admission mode and random epoch, never vault references or material.

- HTTP admission captures an epoch before reading the body and before nonce or
  idempotency waits. Control changes invalidate queued requests.
- The coordinator holds a kernel shared job lock for the entire synchronous
  execution: binding/policy checks, both credential-fetch paths, adapter work,
  and return from custody cleanup. Existing grant checks remain in force.
- Takeover first pauses browser operations and new broker admission, closes
  streams, and disables input. Human mode requires an exclusive job lock,
  proving that all admitted jobs have exited. Resume and lifecycle enable use
  the same barrier.
- If a job remains, takeover/resume is denied and stays paused/input-off. The
  user must retry after the job exits. This is deliberately not automatic
  polling or a successful takeover acknowledgement. Browser callbacks can fail
  and unwind without a viewer thread waiting while holding their browser lock.
- A request deadline does **not** release a still-running job. A disconnected
  caller likewise does not make in-process credential work disappear. Hung
  work keeps control unavailable until it exits or its isolated process is
  demonstrably terminated; do not delete lock files to recover.
- Desktop restart claims a single authority lock and publishes paused state.
  It cannot enable agent or human control while an earlier broker job lives.
  Broker process death releases its kernel lock. An absent authority, corrupt
  state, duplicate authority, stale epoch or lock contention denies admission.
- An uncertain state write or inability to publish paused state relinquishes
  authority entirely. Even readable bytes saying `agent` cannot then admit a
  job; recovery requires restarting the desktop authority.
- Human disconnect stays paused. Neither restart nor disconnect automatically
  reauthorizes queued work.

## Deployment constraints (not yet qualified)

This is a single-host Unix `flock` implementation, not a distributed protocol.
Use an existing private directory, a dedicated volume per browser slot, and
compatible service UID/file permissions. Never mount it into Hermes, expose it
over HTTP, replace/unlink its files while services run, or use NFS. Neither a
second host nor independently duplicated volumes provide exclusion. Credential
operations must remain synchronous: no spawned children/background tasks may
outlive the guarded callback. Desktop/browser process isolation and the mount
trust boundary still require review.

The setting is optional for compatibility with the existing non-desktop
runtime. Therefore deployment validation must establish that **both sides are
wired** before any future credential-enabled rollout. Setting it on only the
desktop does not constrain an unrelated broker. The desktop continues to
reject broker submit configuration even when this guard is configured.

## Reproducible synthetic checks

```sh
.venv/bin/python -m pytest -q tests/unit/test_broker_jobs.py tests/unit/test_desktop_interaction.py tests/contract/test_broker_deadline.py tests/contract/test_broker_secure_runtime.py tests/contract/test_desktop_control_http.py
```

The tests cover both material-fetch paths, stale admission, delayed HTTP bodies,
idempotency queueing, timeout while fetch remains alive, independent broker
process death, desktop authority restart, exception cleanup, failed takeover,
disconnect and explicit resume. HTTP checks need local loopback permission.

`experiments/novnc/candidate_smoke.py` enables the guard in the actual desktop
subprocess and holds synthetic jobs from its separate parent process. It
checks that HTTPS takeover/resume are denied until release, then runs the
existing WSS/A-B-A, process-crash, held-input and lease-recovery matrix. No
Vaultwarden client or real credential fetch is used in that fixture.

### Local evidence — 2026-09-11

- Targeted broker, HTTP, control and Compose suite: **49 passed**.
- Full Linux Python 3.12 suite: **1,186 passed / 14 skipped**. The skips are
  five Docker-CLI checks, three disabled form-adapter cases and six unavailable
  real-browser cases. The targeted Mac suite separately covers desktop Compose.
  Test image: `sha256:dcf0a34fc4183be0662f7b8195aef827049f56aff629b72f24e2b7ca518ea73c`.
- Actual desktop smoke passed with the guard enabled: four A/B/A/restart
  admissions each showed 870,708 owner pixels and zero other-owner pixels;
  each denied takeover/resume while the separate-process synthetic job lived.
  Xvfb/Chromium/x11vnc crashes and expired-lease repair also passed.
- Two initial smoke runs stopped before the job checks because the first frame
  contained no owner canary (diagnosed run: owner=0, other=0). The fixture had
  treated receipt of an HTTP request as render readiness. It now waits for a
  double-animation-frame callback before sampling; pixel assertions are
  unchanged. Two complete runs then passed. This is synthetic render evidence,
  not a universal proof of pixel isolation.
- Final tested local desktop image:
  `sha256:c3ebb28a6a616667d1bbef8e7633004ece2eef5217a67f60a065a4fe3dc839de`.
  This is a local, unqualified image, not a published release.

All smoke containers were disposable, `--network none`, with no host ports or
real credentials. No persistent deployed data or running dev01 service changed.

## Next gates

1. Resolve the existing review block through the approved review path; do not
   substitute a different scan or treat green tests as approval.
2. Qualify deployment wiring, file/process isolation, dependencies and image
   configuration, then rehearse install/rollback on disposable state.
3. Only after approval, qualify real SSO/revocation and ask Tigo for a harmless
   viewer takeover test. Real Vaultwarden onboarding/login is a separate gate.
