# D17 — Fleet slot resource optimization (spec 30 rollout) — APPLY SHEET

**Status:** DRAFT (Tigo ✋ deploys in qualify himself — agent prepares, does NOT deploy).
**Target:** fleet v2 slots (`cb-fleet-v2` Coolify app, mother01 / dev01), image
`ghcr.io/m1k1o/neko/google-chrome:2.9.0` (v2).
**Why:** slots run the heavy config that nearly caused the host-provider
blacklist warning — 1920×1080@30 software VP8, ICE-lite behind NAT.
**Goal:** cut per-slot CPU (esp. encoding) + bandwidth; keep the human UX
(screen still 720p30, still 30 fps for agents via CDP which doesn't stream video).

> **VERIFIED against v2.9.0 source** (`server/internal/config/*.go`, tag
> v2.9.0): all `NEKO_*` names below are real v2 flags. Notes on v2-vs-v3:
> `NEKO_SCREEN` default in v2 source is **1280x720@30** — the fleet's
> `1920x1080@30` is an **override we built**, and it's the heavy one.
> `NEKO_CAPTURE_SCREENCAST_ENABLED` (v3) does **not** exist in v2; audio
> `NEKO_DEVICE` capture is always on in v2 (Opus 128k — small cost, keep).
> No `NEKO_CAPTURE_AUDIO_ENABLED=false` in v2. So the effective levers are
> the video ones below.

---

## A. Baseline (before) — measure first

Run on mother01 (or via SSH from the agent box), **before** changing anything:

```bash
# helper (agent provides /opt/data/d17-measure.py — or copy from repo)
PHASE=BEFORE PROJECT=s7fleet SAMPLES=8 INTERVAL_S=2 \
  python3 /opt/data/d17-measure.py
```

Record the output (mem_used med/p95 MiB, cpu med/p95 %) per slot + router.
This is the **BEFORE** half of the A/B.

## B. Environment variable changes (Coolify UI, app `cb-fleet-v2`)

> Inputs that are identical for both slots (slot-1, slot-2). Keep everything
> else as-is. Change via Coolify UI → stack → Environment Variables (raw
> editor), then **deploy manually** (Tigo) — the UI triggers both slots.

| Variable | From (current) | To | Why |
|---|---|---|---|
| `NEKO_SCREEN` | `1920x1080@30` | `1280x720@30` | **~3× CPU** lives in w×h×fps (spec 30 §5; v3 docs). 720p30 is the v2 default and plenty for a kiosk product browser |
| `NEKO_VIDEO_CODEC` | *(unset → vp8)* | `h264` | software H264 (x264enc veryfast) is far cheaper than software VP8 (spec 30 §5, #156); no GPU needed |
| `NEKO_VIDEO_BITRATE` | *(unset → 3072)* | `2048` | cut bandwidth + encode cost per session (spec 30 §5). 720p30 H264 at 2 Mbps is comfortable |
| `NEKO_NAT1TO1` | *(unset)* | `<mother01-public-ip>` | **required behind NAT** — WebRTC needs the real public IP (spec 30 #621). Without it, ICE-lite silently burns CPU encoding for unreachable clients |
| `NEKO_ICELITE` | `1` | *(remove / `false`)* | stop the lite-agent mode that "encodes for unreachable clients" (spec 30 #621) — with `NAT1TO1` set, the happy path connects cleanly |

> `NEKO_PASSWORD` / `NEKO_PASSWORD_ADMIN` stay as-is (SSO-brokered anyway).
> `CPU_LIMIT`/`mem_limit` stay (2 g / 1.0 cpu per slot — the cgroup throttle,
> spec 30 §5 "the ONLY real throttle").

### Verification after apply (still on mother01)

```bash
# live check — expect screen 1280x720, codec h264
docker exec <slot-1> sh -c 'echo $NEKO_SCREEN; echo $NEKO_VIDEO_CODEC; echo $NEKO_VIDEO_BITRATE; echo $NEKO_NAT1TO1'
```

Also sanity: load `https://cloudbrowser.dev01.pmo.city` in a browser, log in,
confirm the kiosk renders at 720p and video plays (WebRTC connected — not
endlessly "connecting"). If WebRTC fails (ICE), the `NAT1TO1` value is wrong
or the firewall needs the UDP EPR range open.

## C. Measure the tuned fleet (after)

```bash
PHASE=AFTER PROJECT=s7fleet SAMPLES=8 INTERVAL_S=2 \
  python3 /opt/data/d17-measure.py
```

Compare to §A: expect memory ~equal or lower, **CPU markedly lower** (the
encoder is the win), bandwidth per session lower.

## D. Rollback (if needed)

- Revert the two values (`NEKO_SCREEN` → `1920x1080@30`, remove codec/bitrate/nat
  overrides, restore `NEKO_ICELITE=1`) via the same UI → deploy.
- Profiles/downloads are untouched by env changes; sessions survive
  (spec 29 suspend/resume is unaffected).
- If WebRTC misbehaves post-change, first suspect `NAT1TO1` value, not the
  codec: temporarily drop `NEKO_NAT1TO1` + `NEKO_ICELITE` (back to pre-change
  ICE behavior) and re-measure.

---

## E. What this does NOT change

- No image change (`2.9.0` stays — drift pin, spec 30 §5).
- No slot count change (`N_SLOTS=2`); that's D16's job (spec 31), using the
  *measured* post-tuning per-slot budget (FR-16 numbers are the baseline:
  idle ≈ 431 MiB cgroup, ~1 core idle SW encode at 1080p).
- No auth/router change.
