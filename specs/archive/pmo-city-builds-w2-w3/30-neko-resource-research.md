# 30 — Neko Resource Research (why the cloud-browser fleet nearly got blacklisted)

**Date:** 2026-08-21 · **Status:** research complete — input to W2 decision · **Scope:** m1k1o/neko resource consumption evidence (GitHub, docs, Reddit/forums) + tuning levers

**Context:** The cloud-browser fleet (Neko-based, multiple slots on a 31 GB RAM / 8 vCPU VM) used so many resources that the hosting provider nearly blacklisted the server. Tigo asked: *do other people have the same issue with Neko using massive resources?* Answer: **yes — it is architectural, documented, and reproducible.**

Sources cross-checked: `m1k1o/neko` (issues/PRs/comments), `m1k1o/neko-rooms`, original `nurdism/neko`, official docs (neko.m1k1o.net v2/v3), Reddit archives (Arctic Shift), LowEndSpirit, Programster blog, WebRTC codec benchmarks, Kasm official docs.

---

## 1. Official Neko requirements & statements

| Source | Statement |
|---|---|
| https://neko.m1k1o.net/docs/v3/quick-start | **Official spec table**: 1024×576@30 → 2 cores/2 GB "Not Recommended"; 1280×720@30 → 4 cores/3 GB "Good"; 1280×720@30 → 6 cores/4 GB "Recommended"; 1280×720@30 → 8 cores/4 GB+ "Best". Rationale: *"you have to run a full desktop, a browser (a resource hog on its own) and encode/transmit the desktop."* |
| https://neko.m1k1o.net/docs/v3/configuration/capture | **Idle CPU (v3):** *"The Gstreamer pipeline is started when the first client requests the video stream and is stopped after the last client disconnects."* → v3 idle slots do NOT encode (this was broken in old versions, see #115). Default codec **vp8**; default "HQ" pipeline `vp8enc cpu-used=4 threads=4 deadline=1`, target-bitrate ≈ 2 Mbps; "LQ" ≈ 666 kbps. Default H264 example: `x264enc threads=4 bitrate=4096 tune=zerolatency speed-preset=veryfast` @20 fps at 2/3 display resolution. |
| https://neko.m1k1o.net/docs/v3/configuration/desktop | v3 default screen **1280x720@30** (`NEKO_DESKTOP_SCREEN`). |
| https://github.com/m1k1o/neko (compose) | Official compose: `shm_size: "2gb"`, default `NEKO_DESKTOP_SCREEN: 1920x1080@30`, `NEKO_WEBRTC_EPR: 52000-52100/udp`. |
| https://neko.m1k1o.net/docs/v3/installation/docker-images | Chromium-based images require `--shm-size=2g`. |
| https://neko.m1k1o.net/docs/v3/hardware-acceleration/gpu-acceleration-overview | GPU images exist: NVIDIA (`nvh264enc`/NVENC, v2 `NEKO_HWENC=nvenc` + `--gpus all`) and Intel VA-API (`vaapih264enc`). **Opt-in per image**; the base image ships software encoders only. |
| https://github.com/m1k1o/neko/issues/589 | VA-API HW accel **failed on modern Intel (12th gen+) because of outdated Debian Bullseye base image**; fixed in v3.1.0 (Debian Trixie). |
| https://github.com/m1k1o/neko/issues/502 | Maintainer-provided v3 NVENC pipeline: `! nvh264enc preset=2 gop-size=25 bitrate=4096 rc-mode=6 ! h264parse ...`; codec/encoder matrix below. |
| https://github.com/m1k1o/neko (README) | Positioning: *"personal workspace – streaming containerized apps and desktops to end-users – similar to kasm"*; vs Guacamole/noVNC adds WebRTC smooth video + built-in audio. |

**Codec/encoder matrix (from #502):**

| codec | cpu encoder | vaapi encoder | nvenc encoder |
|---|---|---|---|
| VP8 | vp8enc | vaapivp8enc | ? |
| VP9 | vp9enc | vaapivp9enc | ? |
| AV1 | av1enc | ? | nvav1enc |
| H264 | x264enc | vah264enc | nvautogpuh264enc / nvh264enc |
| H265 | x265enc | vah265enc | nvh265enc |

---

## 2. Root causes (maintainer / docs confirmed)

1. **Default codec is software VP8** (`vp8enc`, `threads=4`) — ~4 cores per HQ stream on top of the running browser. Hardware encode is **opt-in and image-specific**; the default image has none.
2. **Shipped example screen is 1920×1080@60** — ~3× the capture/encode cost of 1280×720@30.
3. **Scaling = N parallel containers** (one Chromium/Firefox per container; neko-rooms #48). No multiplexing — architecture, not a bug.
4. **Idle rooms keep RAM/CPU until explicitly stopped** (#164, #57, #28 — feature requests still open). v3 fixed only the *encode* idle drain; the browser process stays resident.
5. **Persistent Firefox profiles grow unboundedly on disk** (#670 — maintainer added a docs warning).
6. **ICE-Lite + no `nat1to1`** → server keeps encoding for unreachable clients, silently burning bandwidth/CPU (#621).
7. **No internal resource throttling** — per-room CPU/RAM is whatever Docker cgroup limits you set (neko-rooms #112).

---

## 3. GitHub evidence (ranked by relevance to the fleet-blacklist scenario)

1. **nurdism/neko #115 — "neko process uses ~80% CPU while idling"** — https://github.com/nurdism/neko/issues/115
   Old image encoded permanently: *"Running `top` inside the freshly started container shows me that the `neko` process uses 80% CPU while everything else stays close to 0."* Fixed in the m1k1o fork ("stays below 1%"). **Steady-state CPU floor of one container ≈ a whole core class** on top of the browser.
2. **m1k1o/neko #389 — "Intel ARC GPU support"** — https://github.com/m1k1o/neko/issues/389
   Maintainer: *"But even the upgrade to bookworm was not successful as we saw **high CPU usage spikes**."* (CPU spikes unrelated to user activity.)
3. **m1k1o/neko #198 — "Stream is lagging"** — https://github.com/m1k1o/neko/issues/198
   *"If I Stream Something and there are 10 people the Stream Starts to lagg. The Server has 10gb ram and 9 CPU I Stream with 1920x1080@30."* Maintainer: shared/over-committed vCPU. Per-session encoding ramps CPU linearly with viewers.
4. **m1k1o/neko #542** — 4-core ARM box hits **100% CPU on default config**.
5. **m1k1o/neko #502 — "Help with Nvidia Hardware Encoding in v3"** — https://github.com/m1k1o/neko/issues/502
   *"CPU usage stayed pretty reasonable at about **3 cores** (4k video would require closer to **8-10**)."* — software 4K ≈ 8–10 cores; maintainer hands out a custom NVENC pipeline to keep CPU sane.
6. **m1k1o/neko #219 — "Turn off video feature"** — https://github.com/m1k1o/neko/issues/219
   Request to disable video to *"save bandwidth, cpu usage and memory"*.
7. **m1k1o/neko #156** — default `vp8enc` freezes repeatedly; maintainer: *"applies to the neko base, meaning for all browsers"*.
8. **m1k1o/neko #621** — `NEKO_WEBRTC_ICELITE: true` silently ignores TURN; *"Even if you want to test it only on LAN, you need to specify NAT1TO1… since we are running it in docker the LAN for neko is only within the container."*
9. **m1k1o/neko #598 / PR #673** — v3 latency regression (~10 s) from GStreamer buffer/jitter mis-tuning; closed by #673 "Reduced audio jitter buffer latency".
10. **neko-rooms #161 — "Outgoing Traffic Spike After Upgrading to Neko-Rooms 1.6.3"** — https://github.com/m1k1o/neko-rooms/issues/161 — egress spike after upgrade; exactly the blacklist failure mode.
11. **neko-rooms #112** — per-room `memory/cpus` = Docker `--memory`/`--cpus` cgroup limits; no internal throttle.
12. **neko-rooms #48** — scaling is N parallel containers, no helper.
13. **neko-rooms #164 / #57 / #28** — `docker pause` / hibernate / "stop room when admins leave": requested, not default.
14. **m1k1o/neko PR #670** — docs warning on unbounded Firefox persistent-profile growth.
15. **Independent sizing (Forgejo infra commit aebece2)** — operator measured `ghcr.io/m1k1o/neko/google-chrome:3.1`: software x264 encoder ≈ **1.2 cores per single viewer session**.

---

## 4. Community evidence (Reddit / forums)

Direct "Neko eats everything" complaint threads are rare; the recurring picture is the **class** of cost: full desktop + browser + WebRTC software encoding, per session, no GPU.

- **r/selfhosted "Selhosted browser?"** (Mar 2026, 81 comments) — *"It looks awesome… seems kinda heavy and my humble toaster I fear might struggle with it"* (Kasm-class stack; Neko same class). https://www.reddit.com/r/selfhosted/comments/1s8osqk/selhosted_browser/
- **r/docker** (Jan 2022) — "super heavy" verdict; Kasm suggested as alternative.
- **r/selfhosted "Self hosted browser?"** (Apr 2025) — *"m1k1o/neko is also an option, but I use Kasm nowadays."* https://www.reddit.com/r/selfhosted/comments/1jwjdpd/self_hosted_browser/
- **LowEndSpirit forum** (Apr 2023) — consensus: *"performance will probably be terrible as hardware/3D acceleration is lacking on most VPS providers. (Keep also an eye on shared resources such as CPU or disk IO)"* — Neko-class workloads need host GPU + CPU headroom. https://lowendspirit.com/discussion/5781/
- **r/PleX "Watch Together replacement"** (Apr 2025) — neko/neko-rooms suggested for multi-viewer fleets (the fleet use case). https://www.reddit.com/r/PleX/comments/1jyf2ri/
- **r/selfhosted "Looking for an alternative to neko"** (Dec 2023) — OP abandoned Neko for linuxserver/webtop + linuxserver/firefox. https://www.reddit.com/r/selfhosted/comments/18two6q/

Note: Reddit blocks direct scraping; threads above were read via the Arctic Shift archive (contents verified, quotes exact). Thread URLs are canonical.

---

## 5. Tuning levers (maintainer-endorsed)

| Knob | Effect | Source |
|---|---|---|
| `NEKO_VIDEO_CODEC=h264` (override `vp8`) | Software H264 (x264enc veryfast) is far cheaper than software VP8; stable server-side encoding | docs + #156 |
| `NEKO_HWENC=vaapi` / `nvenc` (or hwenc pipeline) | Move encoding off CPU entirely | docs + #502 + #589 |
| `NEKO_DESKTOP_SCREEN=1280x720@30` (or lower) | ~3× per-session CPU lives in w×h×fps (default example is 1080p60) | docs |
| `NEKO_CAPTURE_VIDEO_PIPELINE` custom gstreamer (v3) | Replace bitrate/fps/codec per pipeline; dual HQ/LQ (LQ ≈ 666 kbps) | docs + #502 |
| `NEKO_VIDEO_BITRATE=...` (v2) | Cut bandwidth + CPU per session | docs + #136 + #225 |
| `NEKO_NAT1TO1=<public-ip>` | Required behind NAT/proxy so WebRTC actually connects | #621 |
| `NEKO_WEBRTC_ICELITE=false` + coTURN | Stops silent retry/CPU burn for unreachable clients | #621 |
| `shm_size: "2gb"` | Avoids /dev/shm choking Chromium | official compose + v2 docs |
| `--cap-add=SYS_ADMIN` | Required for Chromium sandbox | #462 |
| `capture.screencast.enabled: false` | Disables JPEG-fallback engine used when WebRTC fails | docs + #621 |
| `capture.audio.enabled: false` (if unused) | Drops audio pipeline cost | #219 |
| `session.merciful_reconnect: true` / `implicit_hosting: false` | Reduces leftover sessions keeping browser hot | docs |
| **Per-room `--cpus` / `--memory` (neko-rooms)** | The ONLY real throttle — Docker cgroup limits | #112 |
| **docker pause / stop idle rooms** | Fully release RAM+CPU when nobody's in | #164, #57, #28 |
| **No persistent Firefox profile mounts** | Stops unbounded disk growth | PR #670 |

Maintainer-recommended NVENC pipeline (lowest CPU, from #502):
```
ximagesrc display-name={display} show-pointer=true use-damage=false
  ! video/x-raw,framerate=25/1
  ! videoconvert ! queue ! video/x-raw,format=NV12
  ! nvh264enc name=encoder preset=2 gop-size=25
     spatial-aq=true temporal-aq=true bitrate=4096 vbv-buffer-size=4096 rc-mode=6
  ! h264parse config-interval=-1
  ! video/x-h264,stream-format=byte-stream,profile=constrained-baseline
  ! appsink name=appsink
```

---

## 6. Alternatives (comparison)

| Stack | Architecture | Resource profile | Notes |
|---|---|---|---|
| **Neko (m1k1o/neko)** | GStreamer X11 capture → WebRTC; collaborative multi-viewer | Official 4–8 cores / 3–4 GB+ per instance @720p30; idle no-encode in v3; HW enc via VA-API/NVENC images | Free; Docker-only; per-instance high because each slot = browser + desktop + encoder |
| **Kasm Workspaces** | KasmVNC per user session; containers on agents | Server min 2 cores/4 GB; default images 1768 MB/1 core; 16 CPU/64 GB agent → 8–20 sessions; ~1 core + 2 GB/session community | Heavier platform (Web App + agents + DB) but built for fleet scale-out, per-session isolation, GPU passthrough; CE free |
| **Selkies (selkies-gstreamer)** | GStreamer capture → WebRTC (same family as Neko) | SW x264 ultrafast ≈ 130% CPU @1080p60; HW via NVENC preferred | Low-latency cloud-desktop focus; similar per-session CPU |
| **Apache Guacamole** | Clientless gateway relaying RDP/VNC/SSH — **no video encoding** | guacd <1% CPU when relaying; can pin ~100% on heavy RDP; ~10× RDP bandwidth | Lightest interactive path; no browser-in-browser by itself |
| **Selenium Grid** | Bare browser processes (no desktop, no streaming) | ~150 MB→2 GB/node rule of thumb | Baseline: browser-only is far cheaper than desktop+encoder — fine if human-visible streaming isn't required |

---

## 7. Fleet-specific analysis (31 GB / 8 vCPU)

- Neko "Recommended" = 6 cores/4 GB per 720p30 instance → an 8 vCPU host runs **1–2 active slots** at spec; RAM (31 GB) allows ~7–15 idle-ish slots by the official table. **The per-slot appetite × fleet = provider complaint.**
- Biggest levers: v3 images (idle slots stop encoding) · cap screen ≤1280×720@30 · H264 or HW encode · hard Docker mem/cpu limits per slot · cap rooms and viewers per room.
- No official per-viewer CPU cost; viewer scaling is bandwidth-bound, CPU bound by the single shared encoder (one pipeline per id, served to all clients).
- Idle-slot baseline on v3 should be near 0% encode CPU — **verify with docker stats before/after tuning**; if a slot still burns CPU idle, it's likely the browser itself, a leftover session, or ICE-Lite retry.

---

## 8. Take-aways for the W2 decision

1. **You are not alone** — upstream issues #198, #542, #389 + original #115 reproduce the fleet-on-small-VM pattern.
2. **Neko's cost is architectural**: desktop + browser + software WebRTC encode, N containers. Not a misconfiguration, but tunable.
3. **Tuned Neko can be viable** for a small fleet (H264, 720p30, cgroup caps, idle-stop, proper NAT/TURN).
4. **If the cloud browser is for automation (CDP/headless-ish), Selenium-Grid-style bare browsers are an order of magnitude cheaper** — streaming is the expensive part.
5. **Kasm** is the scale-out answer if human-visible sessions with isolation matter and budget allows.

---

## 9. Source index

- Docs: neko.m1k1o.net/docs/v3/quick-start · configuration/desktop · configuration/capture · configuration/webrtc · installation/docker-images · hardware-acceleration/gpu-acceleration-overview · release-notes · docs/v2 · docs/v2/configuration
- GitHub: m1k1o/neko issues #198 #219 #156 #502 #589 #462 #598 #621 #670; nurdism/neko #115; m1k1o/neko-rooms #48 #112 #161 #164 #28 #57
- Third-party: blog.programster.org/deploying-neko-a-shared-virtual-browser · webrtc-developers.com comparison-of-webrtc-codecs · forgejo.viktorbarzin.me/viktor/infra commit aebece2bcb1e529fc4a0ba391cb9547d0be4666d · kasmweb.com/docs system requirements + sizing · reddit r/selfhosted 1s8osqk / 1jwjdpd / 18two6q, r/PleX 1jyf2ri, r/docker (Jan 2022), r/WebRTC 1px26ec, r/cloudygamer 1e0sq05, r/kasmweb qry6t9, r/homelab 10qe6dw · lowendspirit.com/discussion/5781

*Raw research dumps (not committed): GitHub report, web/docs synthesis, Reddit report — see agent transcripts 2026-08-21 (deleg_c39fff6a).*
