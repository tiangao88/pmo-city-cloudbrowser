#!/usr/bin/env python3
"""Regression: a running ownerless Chrome must be sanitized, not skipped."""
import importlib.util
import os
from pathlib import Path

MODULE_PATH = Path(os.environ.get("RESTART_API", "/opt/data/restart-api-queue-fix.py"))
spec = importlib.util.spec_from_file_location("restart_api_under_test", MODULE_PATH)
ra = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(ra)

calls = []

class Result:
    stdout = "ok"
    stderr = ""
    returncode = 0

ra.slot_user = lambda: None
ra._chrome_running = lambda: True
ra.snapshot_tabs = lambda: calls.append("snapshot")
ra.archive_user = lambda user: (_ for _ in ()).throw(AssertionError("ownerless slot must not archive"))
ra.notify_router_release = lambda user, reason=None: (_ for _ in ()).throw(AssertionError("ownerless slot has no router identity to release"))
ra.wipe_slot_dirs = lambda: calls.append("wipe")
ra.clear_slot_user = lambda: calls.append("clear-user")
ra.clear_chrome_start = lambda: calls.append("clear-start")
ra.subprocess.run = lambda argv, **kwargs: calls.append(tuple(argv)) or Result()
ra._suspended = False

ra._do_suspend_impl()

assert (ra.SUPERVISORCTL, "stop", ra.CHROME_PROG) in calls, calls
assert (ra.SUPERVISORCTL, "stop", ra.TITLE_PROXY_PROG) in calls, calls
assert "wipe" in calls and "clear-user" in calls and "clear-start" in calls, calls
assert "snapshot" not in calls, calls
assert ra._suspended is True
print("PASS ownerless running Chrome is sanitized and marked suspended")
