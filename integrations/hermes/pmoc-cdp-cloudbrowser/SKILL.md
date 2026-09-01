---
name: pmoc-cdp-cloudbrowser
description: "Drive CloudBrowser slots via CDP (wake slot, local lib)."
version: 1.0.0
author: Hermes Agent (D6, spec 26)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [cloudbrowser, cdp, browser-use, pmoc-lan, slots]
---

# pmoc-cdp-cloudbrowser — drive PMO City CloudBrowser slots over CDP

Drive a fleet slot's Chrome (cb-fleet-v2) via its CDP relay, using a
**local vendored copy of the browser-use library** — NOT the Hermes
standard `browser_exec` tool. CloudBrowser has specifics that the
generic tool doesn't handle (idle suspend, wake, queues, slot routing).

## When to use

- Automating a CloudBrowser slot (navigation, tab-switch, download, tab
  management) from the agent box over pmoc-lan.
- Any task that must drive the **real fleet slot** Chrome (not a local
  browser).

## Why not browser_exec

Hermes's standard `browser_exec` drives a **local** Chrome (its harness
attaches to the nearest DevTools endpoint / local profiles). It does
NOT know about CloudBrowser slots: no wake, no slot selection, no
fleet-state awareness. Driving a slot through `browser_exec` fights the
harness's assumptions (e.g. it tried `127.0.0.1:9333`). The vendored
library here connects **directly** to a slot's CDP relay.

## Deployment pitfalls (learned live 2026-08-22)

- **File permissions are SELF-HEALING since 2026-08-22** — mother01 runs
  systemd `cb-normalize.timer` (every 60 s) → `cb-normalize.service` →
  `/usr/local/bin/cb-normalize-volume.sh`, which chowns the scripts
  volume to uid 1000 (neko) + chmod a+rX + verifies. Any future write to
  the volume (agent, manual scp, docker-run) is normalized within a
  minute — a bad-mode deploy can no longer wedge the browser. Sources:
  `/opt/data/cb-normalize-volume.sh|.service|.timer` (local copies).
- **Still be careful at write time** (Tigo directive): the app runs as
  neko (uid 1000), NOT root. Prefer `scp` (preserves 644) over
  `cat > file` (umask 027 → lands `640 root:root`, which broke the
  extension: "Error Loading Extension: could not load javascript
  'content.js'" dialog). After any `cat >`/docker-run volume write, run
  the normalize script or wait ≤60 s for the timer; verify with
  `find $V ! -user 1000 | wc -l` and `find $V -type f ! -perm -o+r`.
- **Extension errors only clear on Chrome restart** — the dialog is
  shown at browser start; clicking OK dismisses it but the extension
  never loads for that Chrome lifetime. A live user's slot needs a
  Chrome restart to pick up fixed perms (brief blip, profile intact).
- **Tabs come back after restart via restart-api's snapshot restore**
  (`$PROFILE/tab-snapshot.json`, watchdog-written every 30s while CDP is
  up, re-opened by the restore consumer at Chrome start; `restore_on_startup=5`
  in prefs only stops Chrome's OWN session restore). To permanently
  remove tabs: close via CDP `/json/close/<id>` AND write
  `{"ts": <now>, "urls": []}` to the snapshot BEFORE the close (kiosk
  Chrome exits when the last tab closes → autorestart → restore reads
  the snapshot you left). Clean snapshot → restore no-ops → homepage
  opens (S1 logic).
- **Kiosk Chrome exits when the last tab is closed** — closing all tabs
  via CDP kills the browser (autorestart=true brings it back). Not a
  bug; use it deliberately: clean snapshot → close tabs → fresh start.
- **`/json/close/<id>` works on 127.0.0.1:9222 in-slot** (plain HTTP);
  through the 9223 relay it fails (raw pipe, no id rewriting) — use
  Playwright `Target.closeTarget` for relay paths.
- In-slot python is 3.9: f-string dict indexing inside heredocs through
  `docker exec -i` can mis-parse — use a variable (`tid = t["id"]`)
  instead of `{t['id']}`.

## Fleet topology (2026-08-21, spec 26)

- Stack cb-fleet-v2, service UUID `okixw2fxnwn1lakxvxajodww` (Coolify).
- mother01, pmoc-lan. Slot containers: `slot-1-*`, `slot-2-*`.
- CDP relay (in-slot, `0.0.0.0:9223` container port) published on host:
  - slot-1 → host `9223` (container 9223)
  - slot-2 → host `9224` (container 9223)
- Restart-api (in-slot, container 9230) published on host:
  - slot-1 → host `9230`
  - slot-2 → host `9231`
- **No ssh tunnel anywhere** — direct pmoc-lan (10.0.0.0/8, host
  firewall DOCKER-USER allows only that subnet for these ports).

## Critical: wake the slot FIRST

Slots idle-suspend: `IDLE_TIMEOUT_MIN=2`, `IDLE_ACTION=suspend`. A
suspended slot has Chrome STOPPED — the CDP relay is up but upstream is
dead → `ConnectionResetError` / curl `000`. **Always wake before
driving**:

```sh
# wake slot-1 — spec 42: user-aware wake; router does this on TAKE only
# (never at offer). Same-user re-wake = no-op; user switch STOPS chrome
# BEFORE swapping the profile (isolation, incident 41).
curl -s -X POST http://10.0.5.1:9230/wake -H "Content-Type: application/json" \
     -d '{"user": "user@example.pro"}'
# other endpoints: GET /idle (slot state+user), POST /suspend,
# POST /release; legacy POST /restart still exists.
# wait for chrome RUNNING + cdp_ok True (poll /health):
curl -s http://10.0.5.1:9230/health
# → {"ok":true,"programs":{...,"google-chrome":"RUNNING",...},"cdp_ok":true}
```

Then wait until `cdp_ok: true` before connecting (poll every ~5s,
Chrome takes ~5-15s).

## Using the vendored browser-use library

The skill vendors a copy of the browser-use library (browser_use +
browser_harness) at `scripts/` — the same version Hermes's CLI uses
(0.1.8 CLI / browser_use 0.13.7). Use it from Python:

```python
import sys
sys.path.insert(0, "<skill>/scripts")  # vendored lib

from browser_use import Browser, BrowserConfig  # etc (browser_use API)
# or drive directly with the CDP helpers:
from browser_harness.helpers import (
    list_tabs, current_tab, switch_tab, close_tab, cdp, js,
    new_tab, page_info, fill_input, click_at_xy, goto_url, wait_for_load,
)
```

Set `BU_CDP_URL` env to the slot's relay before importing/using:

```sh
export BU_CDP_URL=http://10.0.5.1:9223   # slot-1
```

The harness's `get_ws_url()` resolves `{base}/json/version` → WS and
attaches to that browser.

## Standard flow

1. **Wake** (see above).
2. **Connect**: `export BU_CDP_URL=http://10.0.5.1:9223` (slot-1) or
   `:9224` (slot-2); import the vendored helpers.
3. **Drive** with the harness helpers: `page_info()`, `js(...)`,
   `new_tab(url)`, `goto_url(url)`, `switch_tab(list_tabs()[...])`,
   `close_tab(...)`, `cdp("Target.activateTarget", targetId=...)`.
4. **Download check**: files land in the slot's Downloads volume
   (`/home/neko/Downloads` in-slot, `slot-1-downloads` docker volume) —
   surfaced by downloads-api on the docker network + the cloudfiles
   domain (NOT host-published).
5. **Done**: close extra tabs you opened; leave the slot as found.

## Pitfalls (learned D6, 2026-08-21)

- **Suspended slot looks alive**: relay accepts TCP but Chrome is
  stopped → resets. Always check `/health` `cdp_ok` first.
- **`browser_exec` is NOT the path**: it owns a local browser; for
  CloudBrowser use this skill's vendored lib.
- **`cdp()` needs browser-level session** for `Target.*` (works via
  the harness helpers; raw `Target.activateTarget` via a page session
  silently no-ops). Same for **`Browser.setDownloadBehavior`**: the
  harness daemon sends non-`Target.*` methods to the PAGE session where
  the browser-level method is silently ignored → downloads never start.
  Fix (proven D6 2026-08-23): send it on the browser-level WS —
  `GET /json/version` → `webSocketDebuggerUrl` → `{"id":1,"method":
  "Browser.setDownloadBehavior","params":{"behavior":"allow",
  "downloadPath":"/home/neko/Downloads","eventsEnabled":true}}` (use
  `websockets` from the venv). After that, navigating a tab to an
  `application/octet-stream` URL downloads to the slot Downloads dir.
- **github.com is unreachable from slots** (2026-08-23): error page;
  example.com / en.wikipedia.org work. For controlled downloads, serve
  the file from mother01 and navigate the slot to
  `http://<docker-gateway>:<port>/file.bin` (gateway = slot's default
  route, e.g. 10.0.34.1; host firewall allows 10.0.0.0/8).
- **No tunnel**: pmoc-lan direct. `10.0.5.1` is mother01's pmoc-lan IP;
  ports 9223/9224/9230/9231 are host-published, firewall-restricted to
  10.0.0.0/8.
- **Download files** are per-slot (`slot-1-downloads`); verify in the
  volume or via downloads-api, not the host filesystem.

## Verification

```sh
curl -s http://10.0.5.1:9230/health | python3 -m json.tool   # cdp_ok:true
BU_CDP_URL=http://10.0.5.1:9223 <skill>/scripts/venv/bin/python - <<'PY'
from browser_harness.helpers import js, page_info
print(js("document.title"))
PY
```
