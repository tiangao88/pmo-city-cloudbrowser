#!/usr/bin/env python3
"""W3-1A regression: slot API uses the container port on every slot.

The router reaches slots over the compose network, where each service exposes
restart-api on the same container port (9230). Host publishing uses 9230/9231,
but that host-port offset must never be applied to slot-N service DNS calls.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

router_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("router-w31.py")
spec = importlib.util.spec_from_file_location("router_under_test", router_path)
assert spec and spec.loader
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


class Response:
    status = 200

    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


calls: list[tuple[str, float | None]] = []


def fake_urlopen(request, timeout=None):
    url = request.full_url if hasattr(request, "full_url") else str(request)
    calls.append((url, timeout))
    if url.endswith("/health"):
        return Response({
            "ok": True,
            "suspended": True,
            "cdp_ok": False,
            "programs": {"google-chrome": "STOPPED"},
            "user": None,
        })
    return Response({"ok": True})


proxy = object.__new__(router.Proxy)
original = router.urllib.request.urlopen
router.urllib.request.urlopen = fake_urlopen
try:
    for slot in (1, 2):
        assert proxy._slot_health(slot) is not None
        assert proxy._wake_slot(slot, f"owner-{slot}@x.pro") is True
        assert proxy._slot_clean(slot) is True
finally:
    router.urllib.request.urlopen = original

ports = [urlsplit(url).port for url, _ in calls]
expected = [router.SLOT_API_CONTAINER_PORT] * 6
ok = ports == expected
print(("PASS" if ok else "FAIL") +
      f" slot-1/slot-2 internal API port is {router.SLOT_API_CONTAINER_PORT}: {ports}")
raise SystemExit(0 if ok else 1)
