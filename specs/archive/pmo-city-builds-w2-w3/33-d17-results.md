# D17 Results — Tuned fleet resource measurement (AFTER)

Date: 2026-08-21, ~13:35 UTC · Service: `cb-fleet-v2` (`okixw2fxnwn1lakxvxajodww`) · Host: mother01
Deploy: Tigo (agent forbidden in qualify) · Measurement: agent, read-only `docker stats` + CDP page load.

## Config measured (tuned)

| Var | Value |
|---|---|
| NEKO_SCREEN | 1280x720@30 |
| NEKO_VIDEO_CODEC | h264 (software x264enc) |
| NEKO_VIDEO_BITRATE | 2048 |
| NEKO_NAT1TO1 | 145.223.34.130 |
| NEKO_ICELITE | false |
| CPU_LIMIT | 0.5 |
| IDLE_TIMEOUT/GRACE/CHECK | 2 / 1 / 10 |
| mem_limit / shm | 2g / 2gb |

Verified live via `docker inspect slot-1-…`: all vars + NanoCpus=500000000, Memory=2147483648.

## Measurements (median / p95, 15-30 samples)

| State | Slot-1 mem | Slot-1 CPU | Slot-2 mem | Slot-2 CPU |
|---|---|---|---|---|
| Idle (no session) | 261 MiB / 606 | 0.1% / 55.6%* | 442 MiB / 442 | 0.1% / 4.3% |
| Loading (lemonde.fr) | 652 / 675 | 46.4% / 55.5% | 442 / 442 | 0.1% / 3.9% |
| Settled load | 651 / 652 | 43.4% / 52.1% | 442 / 442 | 0.1% / 3.5% |

\* single spike at container start (Chrome cold boot); median 0.1% idle.

Per-process (loaded, slot-1): Chrome RSS sum 738 MiB; cgroup mem 481 MiB at instant of `docker stats --no-stream` (sampled 652 median).

Host-wide (loaded): load 5.6 → slot-1 = ~45% of one core; other load = authentik 36%, open-webui 31%, uptime-kuma 12%, dockerd/traefik, dozzle, etc. Fleet is NOT the host load driver anymore.

## vs FR-16 baseline (2026-08-17, heavy config)

| Metric | BEFORE (heavy) | AFTER (tuned) | Δ |
|---|---|---|---|
| Idle mem (cgroup) | 431 MiB | 261–442 MiB | ≈ same / −170 MiB |
| Idle CPU | 107–146% (~1 core!) | 0.1% | **−99%** |
| Loaded CPU peak | 244% | 55.5% (p95) | **−77%** |
| Settled load CPU | 130–140% | 43.4% | **−68%** |
| Loaded mem | 471 MiB | 652 MiB (2 tabs incl. heavy news page) | +181 MiB (page-dependent, Chrome RSS 738) |

## Interpretation

- **CPU is no longer the risk**: idle burn (VP8 + ICE-lite + 1080p encode loop) is gone — 0.1% vs ~1 core. The blacklist scare driver is eliminated.
- 0.5 CPU cap is comfortable: loaded p95 55% < 100% of the 0.5-core quota; headroom for 2 slots on 1 core.
- RAM: 442 MiB idle / ~650 MiB loaded per slot; FR-16's 2g cap still right; 5 slots ≈ 2.2–3.3 GB warm.
- D16 slot-count math (from these numbers): per-slot budget ≈ 0.5 CPU / 2 GB mem → host 32 GB / 16 cores ⇒ **D16 can safely go 4–6 slots** CPU-wise; memory 2 GB each ⇒ 10+ by mem; **CPU is still the binding constraint at ~0.5–1.0 core/slot loaded**.

## Open notes

- ICE-lite removed → WebRTC now uses the default STUN (stun.l.google.com:19302) with NAT1TO1 pinned; client connection should be verified on first real user session (D10/D1 era).
- `docker stats` %CPU is per-container delta; p95 reported to be robust. cgroup mem vs Chrome RSS sum differ (page cache accounting) — cgroup is the limit-relevant number.
