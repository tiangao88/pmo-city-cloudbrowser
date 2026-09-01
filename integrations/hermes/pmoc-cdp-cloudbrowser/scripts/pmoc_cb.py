#!/usr/bin/env python3
"""PMO City CloudBrowser driver — wake + attach + drive a fleet slot's Chrome.

Local vendored browser-use harness (NOT Hermes browser_exec). CloudBrowser
specifics handled here: idle-suspend wake, per-slot CDP/restart endpoints,
cdp_ok readiness wait.

Usage (slot 1):
    import sys; sys.path.insert(0, "<skill>/scripts")
    import pmoc_cb
    pmoc_cb.wake_slot(1)                 # POST /restart, poll /health cdp_ok
    pmoc_cb.attach(1)                    # exports helpers into this module
    pmoc_cb.js("document.title")
    pmoc_cb.new_tab("https://pmo.city")
    for t in pmoc_cb.list_tabs(): ...
    pmoc_cb.switch_tab(t); pmoc_cb.close_tab(t)

Endpoints (host-published on mother01, pmoc-lan only — DOCKER-USER firewall):
  slot 1: CDP http://10.0.5.1:9223   restart-api http://10.0.5.1:9230
  slot 2: CDP http://10.0.5.1:9224   restart-api http://10.0.5.1:9231
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor"))

# Host-published endpoints (fleet topology, spec 26 / 2026-08-21)
CDP_HOST = "10.0.5.1"          # mother01 pmoc-lan bridge
SLOT_CDP = {1: 9223, 2: 9224}  # slot -> CDP relay host port
SLOT_API = {1: 9230, 2: 9231}  # slot -> restart-api host port

# Default tuning values (cb-fleet-v2)
IDLE_TIMEOUT_MIN = 2
IDLE_ACTION = "suspend"


def _http_get(url: str, timeout: float = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _http_post(url: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def health(slot: int) -> dict:
    """GET restart-api /health for the slot."""
    return _http_get(f"http://{CDP_HOST}:{SLOT_API[slot]}/health")


def wake_slot(slot: int, wait_cdp: bool = True, timeout: float = 90) -> dict:
    """Wake a slot: POST /restart (starts Chrome), then wait cdp_ok.

    Slots idle-suspend (IDLE_TIMEOUT_MIN=2, IDLE_ACTION=suspend): Chrome
    STOPPED, CDP relay up but upstream dead -> connection resets. ALWAYS
    wake before driving. Returns the health payload once cdp_ok.
    """
    h = health(slot)
    ch = h.get("programs", {}).get("google-chrome", "?")
    if ch == "RUNNING" and h.get("cdp_ok"):
        return h
    res = _http_post(f"http://{CDP_HOST}:{SLOT_API[slot]}/restart")
    if not res.get("ok"):
        raise RuntimeError(f"wake slot {slot} failed: {res}")
    if not wait_cdp:
        return res
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            h = health(slot)
            if h.get("cdp_ok") and h.get("programs", {}).get("google-chrome") == "RUNNING":
                return h
        except Exception:
            pass
        time.sleep(5)
    raise TimeoutError(f"slot {slot} CDP not ready after {timeout}s: {h}")


def cdp_url(slot: int) -> str:
    return f"http://{CDP_HOST}:{SLOT_CDP[slot]}"


def attach(slot: int, wake: bool = True):
    """Attach to the slot: wake (optional), set BU_CDP_URL, import helpers.

    Re-exports the browser-harness helpers as attributes of this module so
    callers use pmoc_cb.js / pmoc_cb.list_tabs / ... directly.
    """
    if wake:
        wake_slot(slot)
    os.environ["BU_CDP_URL"] = cdp_url(slot)
    # import lazily so wake/health work even if the lib is missing
    from browser_harness.helpers import (  # noqa: PLC0415
        cdp,
        click_at_xy,
        close_tab,
        current_tab,
        fill_input,
        goto_url,
        js,
        list_tabs,
        new_tab,
        page_info,
        switch_tab,
        wait_for_load,
    )
    for _n in ("cdp", "click_at_xy", "close_tab", "current_tab", "fill_input",
               "goto_url", "js", "list_tabs", "new_tab", "page_info",
               "switch_tab", "wait_for_load"):
        globals()[_n] = locals()[_n]
    return globals()


if __name__ == "__main__":
    slot = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    h = wake_slot(slot)
    print(json.dumps({k: h.get(k) for k in ("ok", "cdp_ok")}, indent=2))
    print("chrome:", h["programs"].get("google-chrome"))
