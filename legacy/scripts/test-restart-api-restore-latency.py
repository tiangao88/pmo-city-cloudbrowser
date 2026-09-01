#!/usr/bin/env python3
"""Regression: an explicit wake starts one prompt restore consumer.

The former path waited for the 30-second watchdog PID poll before even
starting restore_tabs(), then restore_tabs slept another 10 seconds. A human
therefore stared at an empty CfT window for ~25-45 seconds after taking a
slot. The wake path must start the sole consumer immediately; the restore
lock/_restore_done guard still prevents duplicate restores.
"""
import importlib.util
import os
from pathlib import Path

MODULE_PATH = Path(os.environ.get(
    "RESTART_API",
    "/workspace/pmo-city-builds/internal/luna/tools-considered/cloud-browser-service/scripts/restart-api.py",
))
spec = importlib.util.spec_from_file_location("restart_api_under_test", MODULE_PATH)
ra = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ra)

calls = []

class Result:
    stdout = "started"
    stderr = ""
    returncode = 0

class ImmediateThread:
    def __init__(self, target, daemon=False, **kwargs):
        calls.append(("thread", target.__name__, daemon))
        self.target = target
    def start(self):
        calls.append(("start", self.target.__name__))

ra.slot_user = lambda: None
ra._chrome_running = lambda: False
ra.wipe_slot_dirs = lambda: calls.append("wipe")
ra.restore_user = lambda user: calls.append(("restore-user", user)) or True
ra.set_slot_user = lambda user: calls.append(("set-user", user))
ra.clear_chrome_start = lambda: calls.append("clear-start")
ra.record_chrome_start = lambda user: calls.append(("record-start", user))
ra.subprocess.run = lambda argv, **kwargs: calls.append(tuple(argv)) or Result()
ra.threading.Thread = ImmediateThread
ra.restore_tabs = lambda: calls.append("restore-tabs")
ra._suspended = True
ra._need_restore = False
ra._grace_until = None

result = ra._do_wake_impl("montigaud@aikumi.pro")

assert result == {"ok": True, "user": "montigaud@aikumi.pro"}, result
assert ("start", "<lambda>") in calls or ("start", "restore_tabs") in calls, calls
assert ra._need_restore is False, "explicit wake consumer owns the restore"
print("PASS explicit wake starts one prompt restore consumer")
