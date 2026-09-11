# M1 source qualification — 2026-09-11

## Scope and source

M1 implementation was authorized by Tigo. Development used the standalone Mac
checkout on branch `feat/m1-owner-continuity`; committed Git bundles transferred
the exact revisions to the separate Linux qualification checkout. No GitHub
push/merge, image publication, live deployment, profile migration or live grant
provisioning was performed.

Final tested source: `37e50c61fa5332c10d44e43d37e5463b45ccae77`.
This evidence and its documentation links are a subsequent documentation-only
commit; the tested runtime and tests are unchanged.

## Qualification environment

- Host: mother01; Coolify `pmo-city` / `development`.
- Container: `hermes-agent-gf68z1riv5f082shjcusvosw`, user `hermes`.
- Dedicated checkout: `/opt/data/cloudbrowser-codex/repository`, detached at
  the tested source. The original Hermes workspace was not edited.
- Linux Python 3.13.5, native OpenSSL, real Chromium at the existing qualification
  path, Compose v5.5.0 from the separate test-tools directory.
- All browser/custody fixtures use disposable profiles, localhost applications
  and synthetic secrets. No employee sign-in or customer data was used.
- This checkout shares the Hermes container's processes/environment; it is not
  a separately sandboxed container. See [development workflow](../DEVELOPMENT.md).

## Results

At the final tested source:

- `uv run make check`: **1030 passed, 3 skipped**, 147.25 seconds; all six
  specification/sensitive-file/installation/release/image validators passed.
- The only skips are the three intentionally disabled production-form
  integration cases. Real-Chromium and Compose checks ran; none were skipped.
- `uv run make cloudfiles-boundary`: **80 passed**, 0.21 seconds.
- `uv run python -m compileall -q src tests`: passed.
- `git diff --check`: passed; Linux working tree clean after verification.
- Focused continuity/custody run at `47b2619`: **37 passed**, including real
  browser state/download continuity. Its full suite also passed, **1030 passed,
  3 skipped**. The final revision additionally rejects restarting an unconfirmed
  live process while retaining its profile lease.
- Mac verification included **15 browser/profile cases** and **12 documentation/
  layout/spec cases**. Linux, not the Mac, is the authoritative crypto/browser
  full-suite result.

The initial owner/consent tests failed before implementation. The first Linux
candidate exposed six failures: three outdated boot/watcher test doubles, two
revoked-grant reporting regressions, and real Chromium leaving a singleton after
signal-based shutdown. Production now requests graceful `Browser.close` before
the forced-stop fallback. Existing revoked-grant behavior is preserved, and
boot tests exercise the shared watcher registry. No gate was disabled to pass.

## Acceptance established

- A → B → A with a fresh second-slot process: Alice's native tabs, application
  cookies, local storage and actual downloaded file return; Bob starts without
  Alice's state. A separate lease test rejects concurrent same-profile slot use.
- Owner paths and download attribution follow stable principal/profile identity,
  not slot or generation. Pending downloads stay with their owner.
- Symlinked owner paths and uncertain singleton ownership fail closed. Failed
  termination retains the lease and cannot be followed by another launch.
- Existing unpartitioned profile/download data is not silently adopted.
- Explicit durable consent survives restart/new tab/generation; cross-owner,
  profile and site lookups fail. Authorized synthetic credential use succeeds
  for a fresh binding and rejects revoked handles or stale epochs.
- Existing exact grants remain exact. Switching consent mode requires explicit
  prior revocation; active mixed authorization modes are rejected.

## Not established by M1

- Independent broker/security release approval remains open from M0. Passing
  tests are not a security GO verdict.
- No current-source image qualification or hosted user acceptance. Live services
  still need the separately authorized release and rollout workflow.
- Employee consent UI, first-task/login journey and live viewer takeover remain
  M2/M3 work. A revoked grant does not log out an existing application session.
- Automated uncertain-crash recovery, multi-host storage/locking, and unattended
  migration of old personal data are not qualified. Follow the
  [migration/recovery checklist](../M1-MIGRATION.md).

No testing action is required from Tigo for this source increment. Real-site
account qualification and employee-facing acceptance will require an explicitly
approved test environment/account and, when appropriate, the user's participation.
