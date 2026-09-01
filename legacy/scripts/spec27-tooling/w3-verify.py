#!/usr/bin/env python3
"""W3 watchdog-restore fix verification (slot-2).

Simulates a Chrome self-exit (the supervisord-autorestart case the old
watchdog missed) and asserts the watchdog auto-restores the snapshot tab
without a POST /restart.
"""
import json, subprocess, sys, time, urllib.request

PORT = 9232  # slot-2 local tunnel
TUNNEL_PID = None


def ssh(cmd, timeout=40):
    return subprocess.run(
        ["ssh", "-i", "/home/hermes/.hermes/home/.ssh/id_ed25519_mother01",
         "-o", "ConnectTimeout=15", "root@mother01.on-ai.sbs", cmd],
        capture_output=True, text=True, timeout=timeout)


def local_cdp():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5) as r:
        return json.load(r)


def pages():
    return [t["url"] for t in local_cdp() if t.get("type") == "page"]


def wait_for(pred, timeout, desc):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = pred()
            if last:
                return last
        except Exception as e:
            last = f"ERR {e}"
        time.sleep(2)
    raise AssertionError(f"timeout waiting for {desc}; last={last}")


def main():
    global TUNNEL_PID
    # 1. tunnel to slot-2 CDP if not already up
    try:
        pages()
        print("tunnel already up")
    except Exception:
        print("starting tunnel...")
        TUNNEL_PID = subprocess.Popen(
            ["ssh", "-i", "/home/hermes/.hermes/home/.ssh/id_ed25519_mother01",
             "-o", "ExitOnForwardFailure=yes", "-N",
             "-L", f"{PORT}:127.0.0.1:9222", "root@mother01.on-ai.sbs"])
        time.sleep(3)
        wait_for(lambda: _try(pages), 15, "tunnel")

    # 2. baseline: one pmo.city tab
    print("baseline pages:", pages())
    assert any("pmo.city" in u for u in pages()), "no pmo.city tab"

    # 3. snapshot is current (watchdog ticks every 30s)
    time.sleep(35)
    snap = json.loads(ssh("docker exec slot-2-okixw2fxnwn1lakxvxajodww "
                         "cat /home/neko/.config/google-chrome/tab-snapshot.json").stdout)
    print("snapshot:", snap)

    # 4. kill the main chrome process (simulates a crash/self-exit)
    pid = ssh("docker exec slot-2-okixw2fxnwn1lakxvxajodww sh -c "
              "'for p in /proc/[0-9]*; do c=$(tr \"\\0\" \" \" < $p/cmdline 2>/dev/null); "
              "case \"$c\" in *remote-debugging-port*) echo ${p#/proc/};; esac; done'").stdout.strip()
    print("chrome main pid:", pid)
    assert pid, "no chrome pid"
    ssh(f"docker exec slot-2-okixw2fxnwn1lakxvxajodww kill {pid}", timeout=20)

    # 5. watchdog should detect pid change + empty state and restore within ~90s
    def restored():
        try:
            ps = pages()
            return any("pmo.city" in u for u in ps)
        except Exception:
            return False
    wait_for(restored, 180, "auto-restore after self-exit")

    print("PASS: after self-exit, watchdog auto-restored pmo.city within 180s")
    print("final pages:", pages())

    # 6. watchdog log evidence
    log = ssh("docker logs --since 3m slot-2-okixw2fxnwn1lakxvxajodww 2>&1 "
              "| grep -E \"watchdog: chrome pid changed|tab-restore\" | tail -5").stdout
    print("--- watchdog log ---")
    print(log or "(no matching log lines yet — may need a few more seconds)")
    assert "watchdog: chrome pid changed" in log or "tab-restore" in log, "missing watchdog evidence"


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


if __name__ == "__main__":
    main()
