# Browser sidecar integration (development scaffold)

The browser-side adapter is exposed by the `browser` service on port `9230`.
It talks to the local Chrome HTTP JSON endpoint (`CB_CHROME_HTTP_URL`, default
`http://127.0.0.1:9222`) and exposes only the restricted lifecycle/page API:

- `GET /browser/readiness`
- `GET /browser/pages`
- `POST /browser/start`
- `POST /browser/stop`
- `POST /browser/pages/open`
- `POST /browser/pages/close-empty`

The slot supervisor consumes it through `CB_BROWSER_API_URL` (default
`http://browser:9230`). The browser service reports only its server-derived
owner and binding generation; it does not expose raw CDP, evaluation,
cookies, storage, network bodies, or credentials.

`browser-overlay.yaml` is a deployment overlay for the compose scaffold. It
adds the browser sidecar and the supervisor's endpoint/binding environment.
The release remains non-installable until the browser process lifecycle,
viewer/authentication, queueing, and CI/staging image qualification gates are
complete.
