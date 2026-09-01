# FR-16 — Capacity measurements (W1, dev01)

> Measured 2026-08-17 on the W1 POC (dev01, PMO City dev): n.eko viewer,
> Chrome for Testing 128.0.6613.137 (`cft-chrome-128`), 1920×1080, window
> pinned by window-manager watcher, single user, idle + Wikipedia article
> load. Method: `docker stats` (cgroup) + per-process VmRSS scan in-container.

## Raw numbers (single browser container)

| Metric | Idle | Loaded (Wikipedia article) |
|---|---|---|
| Container memory (cgroup, docker stats) | **431 MiB** | **471 MiB** (peak sample) |
| Per-process RSS ceiling (sum, shared pages counted per-proc) | ~1.36 GB | — |
| CPU (docker stats) | **~107–146 %** | peak **244 %**, settles ~130–140 % |
| Chrome processes | 12 procs / 1068 MB RSS (sum) | — |
| neko (incl. Xvfb stack) | 267 MB RSS (5 procs) | — |
| pulseaudio / other | 8 MB / 19 MB | — |
| Container memory limit | **none set** (`HostConfig.Memory=0` → host 31.34 GiB) | — |

## Interpretation vs FR-16 locks

- **≈1–2 GB/container RAM limit (FR-16):** real footprint is ~0.5 GB
  (cgroup) — a **2 GB `--memory` cap per browser container** is comfortably
  safe and is the recommended deploy setting (not currently set on dev01).
  Reserve at deploy/W1-wrap time.
- **MAX_RUNNING_BROWSERS = 5, unlimited parked (off):** 5 running × ~0.5 GB
  ≈ 2.5 GB of warm RAM (plus park = 0 while off) — fits a modest host.
- **CPU is the real capacity driver, not RAM:** ~1 core idle per container
  (neko continuously captures+encodes the 1920×1080 Xvfb even when idle).
  At 5 running browsers → ~5+ cores busy just idling. W2 optimization
  candidates: neko idle frame-rate cap / screen-follow resize (09-viewer-evaluation).
- **Shared-memory caveat:** Chrome's 12 processes share pages; per-process
  RSS sum (~1.36 GB) overstates the container footprint (cgroup 431 MiB is
  the number to use for capacity math).

## Files / evidence

- Method scripts: `fr16-measure.py`, `fr16-breakdown.py` (repo, spike/viewer-neko).
- Live state: viewer-ism3def container, dev01 (mother01), 2026-08-17.
