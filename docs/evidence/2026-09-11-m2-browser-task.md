# M2 qualification and dev01 acceptance — 2026-09-11

## Page-reading follow-up

The user's `pmo.city` task exposed an additional observation limit: the public
page contained 4996 bytes of visible text, while the browser rejected text over
4096 bytes. The router also discarded the backend error code.

Runtime source `2e300efc359d8b5706d8b84a30058fa99e9e01f9` now returns a UTF-8-safe
excerpt with an explicit truncation marker within the existing 4096-byte limit.
URL/title and input limits remain unchanged. Known action failures retain their
error code through the router; unknown codes and failed response bodies are not
forwarded. A real-Chromium regression covers a large page containing emoji and
accented text; router regressions cover safe errors and unknown-error suppression.

CI run `34623825124` passed all validators and **1078 tests, 7 skipped**, then
qualified all nine images. Release commit `b6fc6e1` pins those images. The dev01
deployment reached ten healthy containers with zero application restart counts.
A direct authenticated check from the dashboard container confirmed `pmo.city`
page reading returns `ok`, 4096 bytes of text and the truncation marker. A
deliberately nonexistent tab returns `browser_unavailable` through the bridge.

The roster's “anonymous” entry was a waiting record without display-email
metadata. The label now reads “User (display name unavailable)”. The owner was
not established or removed. Waiting records currently have no expiry; abandoned
queue cleanup remains an explicit follow-up. Missing display metadata alone is
not evidence of unauthenticated access.

The earlier qualification records below remain historical evidence; the current
runtime and release references are the page-reading follow-up above.

## Outcome and source

M2 is source-qualified, image-qualified, deployed and accepted for its bounded
first-browser-task scope. Development used the standalone Mac checkout on
branch `feat/m2-first-browser-task`; the branch remains unmerged.

- Runtime image source: `face98a96d69443eefbf81516b75525f58b9a62b`.
- Release pin/deployment metadata: `34246d2cfa6d6aea9b41cf038bb9c53e5dd4f092`.
- Image qualification: GitHub Actions run `34610008200`.
- Environment: Coolify service `nievufka0cggf82cregyihav`, behind
  `cloudbrowser2.dev01.pmo.city`.

The isolated Hermes test profile has a user-supplied TinyAuth-compatible
session cookie in its own secret scope. No cookie value, account identifier,
password, token or OTP is present in this evidence or in the repository.

## Qualification environment

- Linux qualification ran in the dedicated checkout
  `/opt/data/cloudbrowser-codex/repository` inside
  `hermes-agent-gf68z1riv5f082shjcusvosw` on mother01.
- The original Hermes development checkout remained clean and unchanged.
- The Mac checkout remained the development source; the Linux checkout was
  used only to reproduce tests, build acceptance and deployment operations.
- Coolify configuration was read through its API and saved as a protected
  pre-deployment snapshot before every compose change.

## Final automated qualification

At `face98a96d69443eefbf81516b75525f58b9a62b`:

- All six specification, sensitive-file, release-manifest, installation,
  image-input and image-workflow validators passed.
- Linux full suite: **1074 passed, 7 skipped** in 155.13 seconds. Four skips
  are Compose-CLI checks unavailable in that isolated virtual environment;
  three are the deliberately disabled production form-login cases.
- Focused router/viewer/Hermes regression suite: **45 passed**.
- GitHub Actions run `34610008200` repeated `make check`, then built and
  independently qualified all nine application images. Every matrix job
  passed the configured non-root user, runtime UID 10001, healthcheck, service
  endpoint and provenance/SBOM checks.
- The immutable digests and per-image records are stored in
  `deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml` and
  `deploy/coolify/image-qualification/`.

The full Mac suite is not the release authority: macOS does not expose the
Linux `libcrypto.so` name expected by the native crypto loader, and its shorter
Unix-domain-socket path limit breaks one long-path fixture. The changed
contract suite passes on the Mac; the complete green gate above is the Linux
result.

## Reliability fixes discovered during acceptance

Acceptance exercised recovery paths that the original first-tab implementation
did not cover. The final source includes these fixes:

- The browser-download volume is prepared for the non-root runtime owner
  before Chromium starts (`9544af1`, qualified release `75212cf`).
- The Hermes bridge reactivates a server-side active session whose browser is
  temporarily unavailable (`f51dfad`).
- Managed Chromium profiles hold an inherited exclusive lease. After an
  abrupt exit, a compatible profile may remove only stale `SingletonLock`,
  `SingletonCookie` and `SingletonSocket` entries after acquiring that lease;
  legacy profiles remain fail-closed (`8e455b4`). A one-time operator cleanup
  applied this rule to the pre-existing dev01 profile.
- If the supervisor still records `READY` after only the browser container was
  restarted, `wake` now reconciles the browser to the authoritative current
  binding before restart (`4177553`).
- The router now preserves a successful `tabs_list` array instead of silently
  dropping it. It revalidates a maximum of 32 entries and copies only bounded
  `tab_id`, query-free HTTP(S) `url` and `title` fields. Malformed upstream
  responses fail closed as `agent_unavailable` (`face98a`).

## Dev01 deployment

- Coolify accepted the exact digest-pinned compose from `34246d2` after a
  protected snapshot was saved.
- All ten containers are healthy: the nine application services plus
  `clamav/clamav:1.4`.
- Every application container's configured image reference exactly matches
  the release manifest; every restart count was zero after convergence.
- External unauthenticated access remains closed by TinyAuth. Authentication
  for acceptance came only from the isolated Hermes profile secret.

## Accepted user journey

The live bridge test against dev01 produced only bounded status/page metadata:

1. `cloudbrowser_start` returned `active` with no error.
2. `cloudbrowser_tabs_list` returned `ok` and a real list (initially empty
   after deployment).
3. `cloudbrowser_tab_open` opened `https://example.com/` successfully.
4. A second `cloudbrowser_tabs_list` returned exactly one usable tab entry.
5. `cloudbrowser_page_info` targeted that returned opaque tab ID and reported
   URL `https://example.com/` and title `Example Domain`.
6. A model-driven one-shot in the isolated `cloudbrowser-test` Hermes profile
   repeated start/recovery, listing and exact-tab inspection through the MCP
   tools and returned `M2 HERMES ACCEPTANCE PASS`.

Browser-only restart testing also established that the session/binding can be
recovered and a fresh exact-tab task succeeds afterward. An abrupt browser
container restart did **not** preserve the already-open example tab. Session
recovery is therefore accepted; crash-time tab continuity remains open and is
not claimed by M2.

## M2 acceptance boundary

M2 establishes authenticated Hermes-to-CloudBrowser control for a bounded
public-page task: start/recover, list tabs, open one HTTP(S) tab, navigate,
click, type ordinary text and inspect bounded page state using exact tab IDs.
The bridge exposes eight mediated tools and provides no raw CDP, cookie,
storage, network, filesystem, process or credential-material surface.

M2 does not establish:

- a live application login, Vaultwarden grant or TOTP/one-time-code journey;
- production ordinary-form login, which remains disabled and fail-closed;
- preservation of open tabs across an abrupt Chromium/container crash;
- a live video viewer, human takeover/resume, screenshots, tab close/activate,
  back/forward, scroll/key input or richer page observation;
- employee self-service credential consent/revocation, owned by M3; or
- the separate independent broker/security GO verdict.

## Dashboard execution follow-up

The user's dashboard test exposed an environment gap in the initial acceptance:
the agent and dashboard containers share Hermes profiles but mount different
`/opt/data` volumes. The bridge executable existed only in the agent container.
The original CLI acceptance therefore did not establish dashboard execution.

The repair places the qualified standalone bridge in the shared test profile at
`runtimes/cloudbrowser-77b7896044262aaf/hermes_mcp.py`, executed with
`/usr/bin/python3`. The original profile configuration was backed up and its
authentication references were preserved. Both containers subsequently passed
MCP connection and discovery of all eight tools.

A model-driven one-shot inside the dashboard container then passed start,
opening Example Domain, listing the created tab and inspecting that exact tab's
title and URL. This verifies the dashboard container's execution environment;
the user should select `cloudbrowser-test` and start a fresh dashboard chat to
load the repaired tools. The default profile has no CloudBrowser registration.
