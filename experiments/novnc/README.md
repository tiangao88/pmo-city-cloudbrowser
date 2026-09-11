# Disposable noVNC feasibility harness

Not a release component. No SSO, broker, Vaultwarden, production profile mounts,
exclusive takeover, owner-switch qualification or public access. The local
session issuer intentionally requires no authentication: use synthetic data only.
Never expose it beyond loopback or forward it to another host.

Build from repository root:

```sh
docker build -f experiments/novnc/Dockerfile -t cloudbrowser-novnc-spike:local .
docker run --name cloudbrowser-novnc-spike --rm --init --shm-size=256m --memory=1g --cpus=2 -p 127.0.0.1:16080:6080 cloudbrowser-novnc-spike:local
```

Open `http://127.0.0.1:16080/fixture-session`. This grants an HttpOnly synthetic
viewer cookie for ten minutes and redirects to noVNC. It is not SSO or account
proof. Direct WebSocket access without that cookie is rejected. This increment
is read-only: x11vnc rejects keyboard and mouse input, independently of client
settings. The original bidirectional spike results below are historical.
No host volumes, Docker socket, environment files or production secrets may be
mounted. Backend/agent/CDP ports remain container-loopback only. All profiles
are disposable. Stop with `docker stop cloudbrowser-novnc-spike`.

The existing BrowserProcess is the sole Chromium launcher. Existing mediated
browser/agent APIs create the fixture tab. Xvfb supplies its display, x11vnc
exports that display, and noVNC/websockify delivers it over WebSockets (no TURN).
Use `docker exec` only for synthetic fixture QA; this is not a new Hermes tool.

Record image ID/package versions, resource measurements and visible input proof.
Package versions are resolved at build time: this experimental image is not
release-qualified or reproducibly pinned. The browser uses the existing
container no-sandbox pattern, not a newly established security boundary.

Production work must add authenticated, owner-bound stream admission, revoke
active connections on rebind, and server-enforced takeover fencing. Client-side
noVNC viewOnly is not authorization. Do not test application credentials here.

## Read-only adapter increment — 2026-09-11

The disposable threaded websockify adapter now uses `LiveViewConnection` for
each connection. It checks cookie admission and exact Origin/path before the
upgrade, polls authority while idle, rechecks outgoing writes (including pending
WebSocket writes), and discards pending data on closure. x11vnc starts with
`-viewonly -nosel -noremote`. No second browser is launched.

Five loopback integration tests passed for missing cookie, revoked cookie,
incorrect Origin/path and revocation of an already-open idle stream:

```sh
docker exec cloudbrowser-novnc-spike python3 /app/experiment/test_proxy.py
```

Headed Playwright/noVNC QA also passed: attempted typing and clicking did not
change the synthetic page; a mediated click still worked and confirmed the
input remained empty. Revoking the fixture cookie disconnected the visible
viewer without reload. The same package.json/preload console issues recorded
below remain. Test image before the final test EOF-guard edit:
`sha256:b9317d8db115d80f9980010200f829853d7c3a7fbdbd3ddd8a03f76ea1f7fac8`.

This is **not production integration**: the issuer admits any local caller as
the fixture owner; cookies use HTTP for the loopback test; no owner switch is
performed. Production must replace the issuer with trusted SSO/router identity,
serialize slot rebind with stream revocation, bound all protocol/transport
operations, and qualify TLS, clipboard handling and teardown. A polling interval
is not an atomic rebind guarantee. Human takeover is not enabled.

## Local feasibility result — 2026-09-11

Tested on macOS/OrbStack (aarch64), with a headed Playwright browser viewing
the loopback endpoint. The existing mediated API opened the synthetic tab,
typed `From mediated agent` and clicked Apply; the noVNC display showed that
result. Mouse/keyboard input through the noVNC canvas then entered
`From human viewer`; mediated `page_info` returned that exact result.
Reloading the viewer reconnected to the same state. This was an API fixture
test, not an end-to-end Hermes task or exclusive-control test.

Whole-container samples: idle before viewer connection 512.8 MiB / 1.67% CPU;
connected after input 529.6 MiB / 1.74% CPU, with a 1 GiB limit and 2 CPU quota.
These single samples are not a load test, capacity estimate or Neko comparison.

Image: `sha256:c9d0646c998e9a45252cb26cf4bc0c073cca7c01418d5f21764c2219b22dd072`.
Packages: Chromium `152.0.7977.82-1~deb12u1`, noVNC `1:1.3.0-1`,
websockify `0.10.0+dfsg1-4+b1`, x11vnc `0.9.16-9`,
Xvfb `2:21.1.7-3+deb12u13`.

Known console issue: Debian's noVNC assets request a missing `package.json`
(404 plus version-fetch error). Display, input and reconnect still passed;
production asset packaging must resolve this. Unused preload warnings also
appeared. TLS, mobile layout, multi-user isolation, stream revocation, broker
fencing and credential non-disclosure were not qualified by this experiment.
