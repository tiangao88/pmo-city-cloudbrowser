# M2 qualification and dev01 deployment — 2026-09-11

## Scope and source

Tigo authorized M2 implementation after M1. Development used the standalone
Mac checkout on branch `feat/m2-first-browser-task`; committed Git bundles
transferred exact revisions to the separate Linux qualification checkout.

Final tested deployment source:
`5bdbcbdc2ba62b1987b3e9af44c0aec45a4725a3`. Nine application images were
built from `ce0ef5df54eda344692d17498cbbb297fe2161fb`, qualified and published by
GitHub Actions run `34594208145`, then pinned in the release at `5157d60`.
The later deployment commit adds only the missing viewer-to-router Compose
wiring and its installation regression test; it does not rebuild image code.

The branch was pushed and the qualified M2 release was deployed to
`cloudbrowser2.dev01.pmo.city` in Coolify. It has not been merged. No employee
sign-in, live grant or real application account was used. An isolated, stopped
Hermes profile is configured as described below; it has no CloudBrowser cookie
and its MCP server remains disabled.

## Qualification environment

- Host: mother01; Coolify `pmo-city` / `development` context.
- Container: `hermes-agent-gf68z1riv5f082shjcusvosw`, user `hermes`.
- Dedicated checkout: `/opt/data/cloudbrowser-codex/repository`, detached at
  the tested source. The original Hermes workspace remained unchanged.
- Real Chromium:
  `/opt/data/browsers/chromium-1228/chrome-linux64/chrome`.
- Compose v5.5.0 was made discoverable only inside the isolated qualification
  virtual environment. The deployed Coolify service was updated separately
  through its API after preserving a protected pre-deployment snapshot.
- Browser/login fixtures used localhost applications, disposable profiles and
  synthetic credentials.

## Results

At the final tested deployment source:

- `uv run make check`: **1067 passed, 3 skipped**, 162.66 seconds. All six
  specification, sensitive-file, release-manifest, installation, image-input
  and image-workflow validators passed. Real-Chromium and Compose checks ran.
- The only skips are the three deliberately disabled ordinary-form integration
  cases. Production form mode remains fail-closed.
- `uv run make cloudfiles-boundary`: **80 passed**, 0.20 seconds.
- Focused M2 browser/login/entrypoint/idempotency suite: **96 passed**, 33.71
  seconds.
- Hermes' installed MCP SDK initialized the exact source's stdio server and
  discovered all eight tools: **PASS**.
- Local and Linux MCP contract/security suite: **20 passed**. All six validators,
  compileall and `git diff --check` also passed on the Mac candidate.

The first GitHub Actions publication attempt, run `34593503855`, stopped in
validation before building images because an incomplete OpenSSL `ctypes`
signature caused a Python 3.12 RSA test segmentation fault. Commit `13c0414`
declares the pointer-bearing RSA functions before their first call and uses the
correct C `long` type for the DER length. The Linux qualification then passed
the complete crypto suite, five additional RSA repetitions, all validators and
the full gate above. No image from the failed run was published or deployed.

The corrected publication run, `34594208145`, passed validation and built,
qualified and published all nine application images. Each image passed its
non-root, health, endpoint and provenance/SBOM checks. The release manifest
pins those exact digests and passed the release validators before deployment.

## Dev01 deployment

- Coolify service `nievufka0cggf82cregyihav` was updated in the `pmo-city` /
  `development` context and reports `running:healthy`.
- All ten containers are healthy: the nine digest-pinned application services
  plus `clamav/clamav:1.4`. The running application image references match the
  qualified release manifest exactly.
- The deployment-scoped broker KEK and Vault base URL were added through
  Coolify's protected environment configuration. Secret values were generated
  or handled only inside the protected host workspace and were not printed or
  copied to the development Mac.
- The first restart exposed a missing `CB_ROUTER_BASE_URL` in the viewer
  Compose wiring. The viewer failed closed instead of starting partially. The
  wiring and a regression test were added in `5bdbcbd`, the stored Coolify
  definition was verified, and the corrected restart converged healthy.
- Unauthenticated public requests to `/` and `/health` return `401`; this
  confirms the external TinyAuth boundary is closed, not an authenticated
  employee journey. Container-native health checks are green.

The first-tab contract/security tests were run before implementation and failed
as expected. The first Linux browser candidate then found an incorrect expected
error envelope and an incomplete test fake; correcting those exposed a deeper
owner-rebind race. Production now rechecks principal and generation inside the
browser's serialized action gate before every page side effect. No gate was
disabled to pass.

## Acceptance established

- A fresh real Chromium profile can create one bounded HTTP(S) tab and receives
  the exact target ID created by Chromium.
- The same target is used to type ordinary text, click, read the completed page
  state and list tabs. Unknown/stale targets are rejected; no first-tab
  fallback exists.
- URL, selector, text, tab count and page-state boundaries remain bounded.
  Userinfo, fragments, traversal, unsupported operations and caller-supplied
  ownership fields fail before a browser side effect.
- Browser actions revalidate the current principal/generation at the browser
  boundary, closing the precheck/rebind/action race.
- Synthetic real-Chromium Basic Auth and declared Authentik paths prove exact
  target/origin handling and their configured application-account success
  checks. Wrong origin, target, password/account proof and unsupported stages
  fail closed.
- Durable idempotency tests prove an unknown login outcome is preserved and a
  duplicate request does not automatically perform another fetch/fill.
- Hermes has a supported local stdio MCP entrypoint with eight mediated tools.
  It calls only the authenticated viewer routes, refuses redirects, sends no
  identity/binding headers and contains no raw-CDP or Vaultwarden client.
- The obsolete supported-tree Hermes helper that exposed raw CDP and arbitrary
  page evaluation was removed.
- A fresh `cloudbrowser-test` Hermes profile now exists on mother01. It did not
  clone the default profile's secrets, is stopped, is not the default, and has
  only the reviewed CloudBrowser local skill in addition to Hermes' builtin
  core skill. The bridge is installed in a dedicated virtual environment and
  registered with a profile-secret reference, but remains disabled because no
  CloudBrowser authentication value has been supplied.
- The digest-pinned M2 Compose release is running healthy at
  `cloudbrowser2.dev01.pmo.city`.

## Not established by M2

- No live application, live Vaultwarden grant, employee identity or hosted
  browser journey has been accepted. Synthetic application-account proof is
  not evidence that a specific customer site is qualified.
- The Hermes MCP bridge is installed/configured but not authenticated or
  enabled. A controlled acceptance still requires one distinct
  TinyAuth-compatible authorization value for that profile (or a time-bounded
  session cookie), supplied through Hermes secret scope and never chat.
- Interactive OIDC acquisition/renewal for Hermes is not implemented. Shared
  deployment-wide agent identity is prohibited.
- Production form login, TOTP submission and direct one-time-code handoff remain
  unavailable. The current Authentik path detects supported MFA stages but does
  not complete them.
- Page state still rejects bodies beyond the existing 4096-byte bound rather
  than truncating richer observation. Back/forward, scroll/key input,
  screenshots, tab activation/close and download tools remain future work.
- M3 still owns live video, human takeover/resume and employee self-service
  consent/revocation.
- The M0 independent broker/security GO review and authenticated deployment
  acceptance remain separate gates. Test counts and container health do not
  waive them.

The next user participation is a controlled M2 acceptance: sign in to the
deployed CloudBrowser with the non-MFA test account, store that session cookie
in the prepared Hermes profile's secret scope, enable its MCP bridge, and run
one synthetic or approved-site task while observing the exact browser.
