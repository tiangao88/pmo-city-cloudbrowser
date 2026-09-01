# Viewer Component Evaluation — Cloud-Browser Service (2026-08-16)

> **Decision basis for FR-15 (gate Q4, answered 2026-08-16):** reuse an MIT
> viewer component rather than developing one. Mic/camera/audio desirable
> from the start but **best-effort, not a deal breaker**.
> **Verdict: no turnkey MIT viewer with mic+camera+audio exists today.**
> Two permissive candidates fit (noVNC, neko); one strong option is
> excluded (KasmVNC, GPL-2.0). POC spike decides between noVNC and neko.

## Requirements recap (what the viewer must do)

1. Rendered in the **employee's own device browser** after clicking a link
   (no app install, no remote-desktop client).
2. Shows the employee's **single cloud browser live** (FR-2/FR-11) — the
   page that loads *is* the browser.
3. **Reused component** — we do not develop the viewer.
4. License **compatible with the proprietary bridge** (B2): MIT preferred,
   permissive-compatible (Apache-2.0 / MPL) accepted; **no copyleft**.
5. Media best-effort: audio desirable (meet calls), mic/camera only if the
   component provides it.

## Candidates (verified via GitHub API + repos, 2026-08-16)

| Component | License | Stars | Audio | Mic/Cam | Fit |
|---|---|---|---|---|---|
| **noVNC** (`novnc/noVNC`) | **MPL-2.0** (API reports NOASSERTION; project license = MPL-2.0) | ~13.9k | ❌ no audio | ❌ | ✅ page-only VNC client; needs a VNC server + Xvfb sidecar |
| **neko** (`m1k1o/neko`) | **Apache-2.0** (verified LICENSE file) | ~22k | ✅ built-in (WebRTC) | ⚠️ open issue #400 — bidirectional audio not native | ✅ self-hosted virtual browser in Docker; WebRTC |
| **KasmVNC** (`kasmtech/KasmVNC`) | **GPL-2.0** (verified) | ~5.2k | ✅ | ⚠️ | ❌ **copyleft — excluded for the proprietary bridge** |
| **Apache Guacamole** (`apache/guacamole-client`) | **Apache-2.0** | ~1.7k | ✅ (RDP path) | ⚠️ RDP input | ⚠️ heavier; RDP/VNC gateway, not CDP-native |
| **chrome-remote-interface** (`cyrus-and/…`) | **MIT** | ~4.5k | n/a (lib) | n/a | ⚠️ building block, not a viewer — using it = developing the viewer |

## Analysis

- **noVNC (MPL-2.0)** — the classic browser-based VNC client. Page-only (no
  audio, no mic). MPL-2.0 is file-level copyleft: fine to embed in a
  proprietary product **as long as the noVNC files keep their MPL notice**
  (same treatment as MIT for practical purposes, slightly stricter). Needs a
  VNC server (TigerVNC/x11vnc) on the browser container + Xvfb — our Chromium
  is headed, so an X display already exists in the design.
- **neko (Apache-2.0)** — a self-hosted **virtual browser in Docker** using
  **WebRTC**: built-in audio, multi-participant, embeddable. Closest to our
  needs for media. Two caveats:
  - **mic input is an open issue** (#400, bidirectional audio not native) —
    audio-out (hear) works, audio-in (speak) is not there yet;
  - neko **is a full browser product** (its own Chromium/Firefox + X server).
    Our architecture controls **our** Chromium via CDP (browser-use). The
    spike must verify whether neko's WebRTC streaming can attach to **our**
    CDP-controlled Chromium (e.g. stream an X display that our Chromium
    renders into), or whether we run neko's browser and drive it via CDP
    (`--remote-debugging-port`) instead.
- **KasmVNC (GPL-2.0)** — modern noVNC fork with audio — **excluded**:
  GPL-2.0 copyleft cannot be embedded in the proprietary PMO City bridge
  (B2). (Kasm the company dual-licenses commercially; out of scope.)
- **Apache Guacamole (Apache-2.0)** — mature browser-based remote-desktop
  gateway; audio works over the RDP path only (needs Xvfb + xrdp shim), mic
  via RDP input is experimental. Heavier than the other options; fallback if
  noVNC/neko fail.
- **chrome-remote-interface (MIT)** — CDP library with a screencast example;
  using it to build the viewer = **developing that part** (what Tigo ruled
  out). Reference only, unless the POC shows component reuse is unviable.

## Recommendation (for POC spike on dev01)

1. **Primary: neko (Apache-2.0)** — only permissive option with **built-in
   audio**. Spike: attach neko's WebRTC streaming to our CDP-controlled
   Chromium (or run neko's browser with `--remote-debugging-port` and drive
   it via browser-use). Verify: audio-out, persistence, RAM, control path.
2. **Fallback: noVNC (MPL-2.0)** — page-only viewer over TigerVNC on the
   existing headed Chromium. Simplest integration, no media.
3. **Mic/camera**: not available in either permissive component today —
   **deferred** (matches Tigo's "not a deal breaker"). If meet calls become
   a hard requirement, re-evaluate (neko issue #400 may land, or a small
   WebRTC glue piece — that would be developing the missing part, flagged
   for later).

## Open points for the spike

- ~~Can neko stream an **externally controlled** Chromium, or must its own
  browser be used (and driven via CDP)?~~ **RESOLVED 2026-08-17:** neko's own
  Chromium is used, driven via CDP (`--remote-debugging-port=9222`, loopback
  in-container). WebRTC streaming + CDP control work simultaneously.
- RAM/CPU cost of the streaming path vs page-only.
- SSO integration (Tinyauth in front of the viewer route, FR-3).
- Capacity interaction: a **running viewer** counts against
  `MAX_RUNNING_BROWSERS` (FR-16) — viewer idle timeout vs "never expires"
  (FR-2) needs a concrete rule (viewer disconnect ≠ browser destroy).

## Browser engine decision (2026-08-17) — stay on Chrome for Testing 124

**Decision (Tigo-approved): keep CfT 124.0.6367.78 as the browser engine for
W1/W2.** Pinned into the profile volume (survives container recreates).

- **Why CfT, not stock Chrome:** the neko 2.9.0 stock builds (Chrome 151/133
  era) broke CDP automation: `Target.attachToTarget` fails `-32001` and page
  websockets hang. CfT 124 was the first version verified fully working
  (broker → CDP → login-ok E2E, 2026-08-17). The pin is a stability measure,
  not a developer-tool preference.
- **CfT vs standard Chrome:** same Chromium engine (official Google build,
  the default for Playwright/Puppeteer). Differences that matter here:
  - *No auto-update* → exact version pinning, reproducible fleet. Standard
    Chrome's auto-update is precisely the failure mode that already bit us
    (silent CDP breakage on 133/151) and cannot be pinned in a fleet.
  - *No Widevine DRM* → DRM-protected streams (Netflix, myCANAL, some client
    portals) will not play. **Revisit only if** a client case requires DRM:
    then either standard Chrome pinned via apt version-hold (+ auto-update
    disabled), or Widevine CDM sideload into CfT (possible, gray area).
- **W2 optional:** bump-test newer CfT (126/128/13x) with a CDP regression
  check — 124 was pinned as "first that worked", not "best". Not required to
  ship W1/W2.
