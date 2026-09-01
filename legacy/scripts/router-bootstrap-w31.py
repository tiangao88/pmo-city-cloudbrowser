#!/usr/bin/env python3
"""Local-test bootstrap for the W3-1A router (repo copy).

Monkeypatches socket.getaddrinfo so the router's `slot-N` service-DNS
calls resolve to 127.0.0.1 in the local harness, then execs the sibling
router.py (the deployed router source). Mirrors the staged
/opt/data/router-bootstrap-w31.py but is repo-relative and loads the
repo router, so the focused readiness suite runs against the exact
committed source.
"""
from __future__ import annotations
import socket
import sys
from pathlib import Path

real = socket.getaddrinfo

def patched(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host.startswith("slot-"):
        host = "127.0.0.1"
    return real(host, port, family, type, proto, flags)

socket.getaddrinfo = patched
path = Path(__file__).resolve().parent / "router.py"
source = path.read_text(encoding="utf-8")
namespace = {"__name__": "__main__", "__file__": str(path)}
exec(compile(source, str(path), "exec"), namespace)
