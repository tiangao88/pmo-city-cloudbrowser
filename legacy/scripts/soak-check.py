#!/usr/bin/env python3
"""D9 soak daily check (no_agent cron, deliver origin) — tracks cb-fleet-v2.

Target: Coolify service cb-fleet-v2-okixw2fxnwn1lakxvxajodww (the NEW
fleet app: router + slot-1 + slot-2 + janitor + clamav on mother01).
Explicitly NOT the old cloudbrowser-w1 app (viewer-4guplgcrvug7l7h64m2cxkm1).

DoD D9: "zero manual interventions — Chrome crash self-heals < 1 min".
Prints a status line ALWAYS (soak log), with explicit ALERT lines on any
anomaly.

Checks (all container discovery via compose-project label, so names/IPs
can drift without breaking the script):
  - all 5 fleet containers present and running (docker inspect)
  - router /fleet/status (:8081) — saturated?
  - slot-1/slot-2 restart-api /health (:9230): google-chrome RUNNING,
    tabs restored, cdp_ok
  - slot downloads-api /health (:9231)
  - container Memory cap still 2 GiB + CPU cap 1.0 core (NanoCpus)
  - janitor + clamav containers alive
"""
import json
import subprocess
import urllib.request

SERVICE_UUID = "okixw2fxnwn1lakxvxajodww"
SSH = ["ssh", "-i", "/home/hermes/.hermes/home/.ssh/id_ed25519_mother01",
       "-o", "ConnectTimeout=10", "root@mother01.on-ai.sbs"]


def ssh_out(cmd):
    """Run a command on mother01 host (not inside a container)."""
    try:
        r = subprocess.run(SSH + cmd, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception as e:
        return f"ssh error: {e}"


def get(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}


def fleet_containers():
    """Discover fleet containers -> {role: name}.

    Primary: compose project label (= Coolify service uuid). Fallback:
    name prefix match (slot-1-<uuid>, router-<uuid>, ...) in case the
    label filter ever fails while containers exist.
    """
    out = ssh_out(["docker", "ps", "-a", "--filter",
                   f"label=com.docker.compose.project={SERVICE_UUID}",
                   "--format", "{{.Names}}"])
    if out.startswith("ssh error"):
        return {"_error": out}
    roles = {}
    if out:
        for name in out.splitlines():
            for role in ("router", "slot-1", "slot-2", "janitor", "clamav"):
                if name.startswith(role + "-"):
                    roles[role] = name
                    break
    if len(roles) < 5:
        # Fallback: name prefix match across all containers
        out2 = ssh_out(["docker", "ps", "-a", "--format", "{{.Names}}"])
        if not out2.startswith("ssh error") and out2:
            for name in out2.splitlines():
                for role in ("router", "slot-1", "slot-2", "janitor", "clamav"):
                    if role in roles:
                        continue
                    if name.startswith(role + "-" + SERVICE_UUID):
                        roles[role] = name
    if not roles:
        return {"_error": "no containers found for fleet project "
                          f"({SERVICE_UUID})"}
    return roles


def inspect(container, fmt):
    return ssh_out(["docker", "inspect", container, "--format", fmt])


def main():
    lines = []
    alerts = []

    roles = fleet_containers()
    if "_error" in roles:
        print(f"Soak day check — FLEET DISCOVERY FAILED: {roles['_error']}")
        print("ALERT: cb-fleet-v2 containers not found on mother01")
        return

    missing = [r for r in ("router", "slot-1", "slot-2", "janitor", "clamav")
               if r not in roles]
    if missing:
        alerts.append(f"ALERT: fleet containers missing: {missing}")

    states = {}
    ips = {}
    for role, name in roles.items():
        st = inspect(name, "{{.State.Status}}")
        states[role] = st
        ip = inspect(name, "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}")
        ips[role] = ip.split()[0] if ip and not ip.startswith("ssh error") else ""
        if st != "running":
            alerts.append(f"ALERT: {role} ({name}) state={st}")

    lines.append("Soak day check — cb-fleet-v2 "
                 f"(router={states.get('router')}, slot-1={states.get('slot-1')}, "
                 f"slot-2={states.get('slot-2')}, janitor={states.get('janitor')}, "
                 f"clamav={states.get('clamav')})")

    # Router fleet status
    rip = ips.get("router", "")
    if states.get("router") == "running" and rip:
        fs = get(f"http://{rip}:8081/fleet/status")
        if "error" in fs:
            alerts.append(f"ALERT: router /fleet/status unreachable: {fs['error']}")
        else:
            lines.append(f"router fleet: {json.dumps(fs)[:160]}")
            if fs.get("saturated"):
                alerts.append("ALERT: fleet saturated")
    else:
        alerts.append("ALERT: router not probed (not running or no IP)")

    # Per-slot checks
    for role in ("slot-1", "slot-2"):
        ip = ips.get(role, "")
        if states.get(role) != "running" or not ip:
            alerts.append(f"ALERT: {role} not probed (not running or no IP)")
            continue
        h = get(f"http://{ip}:9230/health")
        chrome = (h.get("programs") or {}).get("google-chrome", "UNKNOWN")
        tabs = h.get("tabs", [])
        cdp = h.get("cdp_ok")
        lines.append(f"{role}: chrome={chrome} cdp_ok={cdp} tabs={len(tabs)} "
                     f"({', '.join(t[:50] for t in tabs[:3])})")
        if chrome != "RUNNING":
            alerts.append(f"ALERT: {role} google-chrome is {chrome}")
        if cdp is not True:
            alerts.append(f"ALERT: {role} cdp_ok={cdp}")
        if "error" in h:
            alerts.append(f"ALERT: {role} /health unreachable: {h['error']}")
        dl = get(f"http://{ip}:9231/health")
        if dl.get("ok") is not True:
            alerts.append(f"ALERT: {role} downloads-api down ({dl.get('error', '')})")

        mem = inspect(roles[role], "{{.HostConfig.Memory}}")
        cpus = inspect(roles[role], "{{.HostConfig.NanoCpus}}")
        try:
            mem_g = int(mem) / (1024 ** 3)
            cpu_c = int(cpus) / 1e9
            lines.append(f"{role} caps: mem={mem_g:.1f} GiB cpu={cpu_c:.1f}")
            if int(mem) != 2147483648:
                alerts.append(f"ALERT: {role} memory cap changed ({mem})")
            if int(cpus) != 1000000000:
                alerts.append(f"ALERT: {role} CPU cap changed ({cpus})")
        except Exception as e:
            alerts.append(f"ALERT: {role} caps unreadable ({mem!r} / {cpus!r})")

    # Janitor / clamav alive (already covered by state check above)
    if states.get("janitor") == "running":
        lines.append("janitor: running")
    if states.get("clamav") == "running":
        lines.append("clamav: running")

    out = "\n".join(lines)
    if alerts:
        out += "\n" + "\n".join(alerts)
    print(out)


if __name__ == "__main__":
    main()
