#!/usr/bin/env python3
"""Bootstrap for local router tests: resolve slot-1/slot-2 -> 127.0.0.1
without touching /etc/hosts, then run the real router main()."""
import socket
import sys

_real_getaddrinfo = socket.getaddrinfo


def _patched(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host.startswith("slot-"):
        host = "127.0.0.1"
    return _real_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _patched

sys.path.insert(0, "/opt/data")
import importlib.util

spec = importlib.util.spec_from_file_location("router", "/opt/data/router.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.main()
