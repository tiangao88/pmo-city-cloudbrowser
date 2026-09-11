# M2 source qualification — 2026-09-11

## Scope and source

Tigo authorized M2 implementation after M1. Development used the standalone
Mac checkout on branch `feat/m2-first-browser-task`; committed Git bundles
transferred exact revisions to the separate Linux qualification checkout.

Final tested source: `184d4bca4ca5a4cd7032f8e837ae7ef70a6dee23`.
This evidence file and status links are a later documentation-only commit; the
tested runtime and tests are unchanged.

No GitHub push/merge, image publication, live deployment, Hermes profile
configuration, employee sign-in, live grant or real application account was
used or changed.

## Qualification environment

- Host: mother01; Coolify `pmo-city` / `development` context.
- Container: `hermes-agent-gf68z1riv5f082shjcusvosw`, user `hermes`.
- Dedicated checkout: `/opt/data/cloudbrowser-codex/repository`, detached at
  the tested source. The original Hermes workspace remained unchanged.
- Real Chromium:
  `/opt/data/browsers/chromium-1228/chrome-linux64/chrome`.
- Compose v5.5.0 was made discoverable only inside the isolated qualification
  virtual environment. No deployed Compose resource was rendered or mutated.
- Browser/login fixtures used localhost applications, disposable profiles and
  synthetic credentials.

## Results

At the final tested source:

- `uv run make check`: **1065 passed, 3 skipped**, 151.96 seconds. All six
  specification, sensitive-file, release-manifest, installation, image-input
  and image-workflow validators passed. Real-Chromium and Compose checks ran.
- The only skips are the three deliberately disabled ordinary-form integration
  cases. Production form mode remains fail-closed.
- `uv run make cloudfiles-boundary`: **80 passed**, 0.20 seconds.
- Focused M2 browser/login/entrypoint/idempotency suite: **96 passed**, 33.71
  seconds.
- Hermes' installed MCP SDK initialized the exact source's stdio server and
  discovered all eight tools: **PASS**.
- Local MCP contract/security suite: **19 passed**. All six validators,
  compileall and `git diff --check` also passed on the Mac candidate.

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

## Not established by M2

- No live application, live Vaultwarden grant, employee identity or hosted
  browser journey has been accepted. Synthetic application-account proof is
  not evidence that a specific customer site is qualified.
- The Hermes MCP bridge is not installed/configured in a live profile. A
  controlled acceptance requires one distinct TinyAuth-compatible
  authorization value for that profile (or a time-bounded session cookie),
  supplied through Hermes secret scope and never chat.
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
- The M0 independent broker/security GO review, current-source image
  qualification, release assembly and deployment acceptance remain separate
  gates. Test counts do not waive them.

The next user participation is a separately approved controlled M2 acceptance:
configure the bridge in one Hermes profile, authenticate that profile, and run
one synthetic/approved-site task while observing the exact browser. It should
occur only after choosing the target environment/account and deciding whether
to build/deploy this source first.
