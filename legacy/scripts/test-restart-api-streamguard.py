#!/usr/bin/env python3
"""Regression for Spec 40 stream-guard rescue state handling.

The guard calls restart_neko only after an occupied slot has remained wedged
long enough. It must update the module-level cooldown timestamp instead of
raising UnboundLocalError when assigning it.
"""
import importlib.util
import os
import tempfile
from pathlib import Path

MODULE_PATH = Path(os.environ.get("RESTART_API", "/opt/data/restart-api-streamfix.py"))
spec = importlib.util.spec_from_file_location("restart_api_streamguard", MODULE_PATH)
ra = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ra)

calls = []
sleep_calls = 0

ra.CB_STREAM_GUARD_S = 0
ra.CB_RESET_COOLDOWN_S = 0
ra.NEKO_LOG = os.path.join(tempfile.gettempdir(), "nonexistent-neko-log")
ra._suspended = False
ra._rescue_last = 0.0
ra.slot_user = lambda: "spike-user@aikumi.pro"
ra.neko_wedged = lambda: True
ra.restart_neko = lambda: calls.append("restart") or {"ok": True}

original_sleep = ra.time.sleep

def stop_after_third_sleep(seconds):
    global sleep_calls
    sleep_calls += 1
    if sleep_calls >= 3:
        raise RuntimeError("stop test loop")

ra.time.sleep = stop_after_third_sleep
try:
    ra.stream_guard_loop()
except RuntimeError as exc:
    assert str(exc) == "stop test loop", exc
finally:
    ra.time.sleep = original_sleep

assert calls == ["restart"], calls
assert ra._rescue_last != 0.0, ra._rescue_last
print("PASS stream guard updates module cooldown without UnboundLocalError")
