# Step 19 runtime qualification

- Date: 2026-09-03
- Environment: Coolify PROD, PMO City / `development`
- Service: `cloudbrowser2`
- Coolify service UUID: `nievufka0cggf82cregyihav`
- Instance ID: `cloudbrowser2-dev-v01`
- Release: `0.2.0-dev1`
- Current status: **partial — browser startup blocker fixed; full Step 19 remains open**

## Root cause and correction

The browser image was healthy in CI but the deployed browser container
crash-looped during startup. The persistent profile volume contained stale
Chromium singleton symlinks left by an earlier container:

- `SingletonCookie` → `11268023045038235109`
- `SingletonLock` → `1c3527826419-7`
- `SingletonSocket` → `/tmp/org.chromium.Chromium.WDooI4/SingletonSocket`

All three targets were absent. A throwaway-profile reproduction returned
Chromium exit code `21` with:

> The profile appears to be in use by another Chromium process ... Chromium
> has locked the profile ...

After stopping only the browser container, removing those stale markers, and
starting only that container, Chromium became ready and remained healthy. The
production fix is now in `04441a3`: `BrowserProcess.start()` removes the three
Chromium singleton markers before launching, and
`tests/contract/test_browser_profile_recovery.py` covers the behavior.

The fix was pushed to `origin/main`. GitHub Actions Build images run
`33746220117` completed successfully; all eight jobs passed, including the
browser qualification job and its `image-qualification-browser` artifact.

## Verified acceptance evidence

- All seven deployed child containers are `running` and `healthy`.
- All seven service health endpoints return HTTP 200.
- Browser health reports `browser_state: ready` and the expected instance and
  release metadata.
- Browser CDP `/json/version` reports `Chrome/151.0.7922.173` and a valid
  WebSocket debugger URL.
- Browser profile is mounted from the instance-scoped Docker volume
  `nievufka0cggf82cregyihav_browser-profile`.
- Router, slot state, browser profile, downloads, and broker state use
  instance-scoped volumes prefixed with `nievufka0cggf82cregyihav`.
- `cloudbrowser2.dev01.pmo.city/health` returns HTTP 200.
- `cloudbrowser2.dev01.pmo.city/viewer` returns HTTP 401 without a viewer
  token, as expected.
- The browser image was redeployed through Coolify from the fixed digest; the
  stored compose and live container both reference
  `sha256:5f00814037f4e260a001088a0e1fccd1cf66cefd0d22ba6422e72cd24f9af0c5`.
- A controlled Coolify service restart temporarily stopped all seven child
  containers, then returned the service to `running:healthy`; the browser
  returned with restart count `0` and health `healthy`.
- The public files host is **not yet wired**:
  `cloudfiles2.dev01.pmo.city/health` returns HTTP 302 to
  `https://www.on-ai.sbs/error.html`; no standalone `cloudfiles2` Coolify
  application/container is present.

## Remaining gates

1. Wire the separate `cloudfiles2.dev01.pmo.city` Coolify application to the
   downloads service and verify its authentication and file contract.
2. Exercise persistence across a controlled stack stop/start without removing
   the instance volumes; verify browser profile and downloads state survive.
3. Exercise side-by-side instance isolation with a second, separately scoped
   test instance; verify networks, volumes, state, and service metadata do not
   cross.
4. Exercise viewer binding with an authorized test identity; unauthenticated
   access is verified, authenticated viewer identity is not yet qualified.
5. Exercise rollback from a backed-up state and verify the rollback target and
   instance scope.

No credential operation or credential rotation was performed. With explicit
redeploy approval, the live `cloudbrowser2` stack was changed to the fixed browser
image and restarted through Coolify. Existing unrelated fleet services were not
changed.
