# Browser service

The browser service owns exactly one Chromium process and one owner-bound
profile. It exposes the restricted adapter API on port `9230` and never
exposes raw CDP, cookies, storage, credentials, network bodies, or arbitrary
evaluation.

## Runtime contract

- `CB_CHROME_EXECUTABLE` — absolute Chromium/Chrome executable path.
- `CB_CHROME_HTTP_PORT` — loopback CDP HTTP port, default `9222`.
- `CB_CHROME_HTTP_URL` — loopback Chrome HTTP origin, default
  `http://127.0.0.1:9222`.
- `CB_CHROME_EXTRA_ARGS` — extra Chromium flags; the image default is
  `--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`
  (container-appropriate flags; overridable per deployment).
- `CB_PROFILE_DIR` — absolute persistent profile path, default `/data/profile`.
- `CB_PRINCIPAL_ID` and `CB_BINDING_GENERATION` — server-owned identity binding.
- `CB_PORT` — restricted browser service port, default `9230`.

The browser service auto-starts Chromium at boot (owner/generation-bound) and
recovers crashes through its watcher. The process manager starts Chromium with
a private debugging address and an
explicit profile directory. It waits for a real `/json/version` response,
marks readiness only after validating the browser identity and WebSocket URL,
and reports degraded health when Chrome is unavailable. A watcher detects a
child crash and attempts recovery without changing owner or generation.

The service uses a non-root image user and a per-install `CB_INSTANCE_ID`
volume. The local source build is a development release gate; published
immutable images and the runtime/security acceptance matrix are still required
before `installable: true`.
