#!/usr/bin/env python3
"""D17 fleet A/B resource measurement — run on mother01 (or via SSH).

Baseline (current heavy config) vs tuned (spec 30 levers). Measures the
running fleet containers with a bounded sample, prints a comparison table.

Intended use (Tigo runs deploy step himself):
  1. MEASURE PHASE=BEFORE  -> captures the heavy-config numbers (fleet as-is)
  2. Tigo applies env changes + redeploys (documented in D17 apply sheet)
  3. MEASURE PHASE=AFTER   -> captures the tuned-config numbers
  4. Result table in chat / committed to specs/31-... (after Tigo's go)

Environment:
  PHASE            : BEFORE|AFTER (default BEFORE)
  PROJECT          : Coolify project filter (default 's7fleet')
  SLOT_NAME        : slot container name prefix (default 'slot-')
  SAMPLES          : samples per container (default 8)
  INTERVAL_S       : seconds between samples (default 2)
  LABEL_PREFIX     : optional label prefix to distinguish tuned containers

Writes JSON to ./d17-<phase>.json when a path is given (else prints table).
"""

import json
import os
import re
import subprocess
import sys
import time
from collections import OrderedDict

PHASE = os.environ.get("PHASE", "BEFORE").upper()
PROJECT = os.environ.get("PROJECT", "s7fleet")
SLOT_NAME = os.environ.get("SLOT_NAME", "slot-")
SAMPLES = int(os.environ.get("SAMPLES", "8"))
INTERVAL = float(os.environ.get("INTERVAL_S", "2"))
OUT = os.environ.get("OUT", "")

# CPU accounting caveat: docker stats %CPU = per-container delta between
# samples; a single heavy sample can look like 150%. We report median +
# p95 to be robust.
UNITS = {"kb": 1024, "mb": 1024 ** 2, "gb": 1024 ** 3, "b": 1}


def parse_bytes(s: str) -> float:
    """Parse '431MiB', '431 MiB', '1.2GiB', '512MB', '123 kb' -> bytes."""
    s = s.strip().lower()
    m = re.match(r"([\d.]+)\s*([a-z]*)", s)
    if not m:
        return 0.0
    num = float(m.group(1))
    unit = m.group(2).replace("ib", "b")  # MiB->mb, GiB->gb, KiB->kb
    return num * UNITS.get(unit, 1)


def parse_cpu(s: str) -> float:
    s = s.strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return 0.0


def docker_stats(ctr: str) -> dict | None:
    """One-shot `docker stats --no-stream` row for a container."""
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}", ctr],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip().splitlines()
    except Exception:
        return None
    if not out:
        return None
    parts = out[0].split("|")
    if len(parts) != 3:
        return None
    mem_used = parse_bytes(parts[1].split("/")[0])
    mem_limit = parse_bytes(parts[1].split("/")[1]) if "/" in parts[1] else 0.0
    return {"mem_used": mem_used, "mem_limit": mem_limit, "cpu": parse_cpu(parts[2])}


def main() -> None:
    # Discover fleet containers
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}", "--filter",
             f"name={SLOT_NAME}", "--filter", f"label=com.docker.compose.project={PROJECT}"],
            capture_output=True, text=True, timeout=30,
        ).stdout.split()
    except Exception as e:
        print(f"ERROR: docker ps failed: {e}", file=sys.stderr)
        sys.exit(1)
    containers = sorted(out)
    if not containers:
        print(f"WARN: no containers matched (project={PROJECT}, name prefix={SLOT_NAME}). "
              f"Fleet may be stopped. Nothing to measure.")
        sys.exit(0)

    print(f"D17 measure PHASE={PHASE}  containers={containers}  "
          f"samples={SAMPLES} x interval={INTERVAL}s\n")

    rows = {c: [] for c in containers}
    for i in range(SAMPLES):
        for c in containers:
            s = docker_stats(c)
            if s:
                rows[c].append(s)
        if i < SAMPLES - 1:
            time.sleep(INTERVAL)

    # Summarize
    print(f"{'container':<28}{'mem_used(med)':>14}{'mem_used(p95)':>14}"
          f"{'cpu_%(med)':>12}{'cpu_%(p95)':>12}{'limit':>10}")
    summary = {}
    for c, samples in rows.items():
        if not samples:
            print(f"{c:<28}{'unreachable':>14}")
            continue
        mems = [s["mem_used"] for s in samples]
        cpus = [s["cpu"] for s in samples]
        limit = samples[-1]["mem_limit"]
        mems_sorted = sorted(mems); cpus_sorted = sorted(cpus)
        mem_med = mems_sorted[len(mems_sorted) // 2]
        mem_p95 = mems_sorted[min(len(mems_sorted) - 1, int(len(mems_sorted) * 0.95))]
        cpu_med = cpus_sorted[len(cpus_sorted) // 2]
        cpu_p95 = cpus_sorted[min(len(cpus_sorted) - 1, int(len(cpus_sorted) * 0.95))]
        print(f"{c:<28}{mem_med / 1024**2:>13.0f}MiB{mem_p95 / 1024**2:>13.0f}MiB"
              f"{cpu_med:>11.1f}%{cpu_p95:>11.1f}%"
              f"{(limit / 1024**2 if limit else 0):>9.0f}MiB")
        summary[c] = {"mem_used_med_mib": round(mem_med / 1024**2, 1),
                      "mem_used_p95_mib": round(mem_p95 / 1024**2, 1),
                      "cpu_pct_med": round(cpu_med, 1),
                      "cpu_pct_p95": round(cpu_p95, 1),
                      "mem_limit_mib": round(limit / 1024**2, 1) if limit else None,
                      "n_samples": len(samples)}

    if OUT:
        with open(OUT, "w") as f:
            json.dump({"phase": PHASE, "containers": summary}, f, indent=2)
        print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()