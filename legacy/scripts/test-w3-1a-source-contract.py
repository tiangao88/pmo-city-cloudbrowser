#!/usr/bin/env python3
"""Focused W3-1A source test for active reload readiness gating."""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
p=Path(sys.argv[1]); spec=importlib.util.spec_from_file_location('rt',p); rt=importlib.util.module_from_spec(spec); spec.loader.exec_module(rt)
source=p.read_text()
checks={
 'readiness helper exists':'def _ensure_slot_ready' in source,
 'health contract checks cdp':'obj.get("cdp_ok") is True' in source,
 'health contract checks chrome':'chrome.startswith("RUNNING")' in source,
 'health contract checks owner':'obj.get("user") == email' in source,
 'fresh path gates before landing':'if not self._ensure_slot_ready(k, email):' in source,
 'queue poll gates active':'elif not self._ensure_slot_ready(k, email):' in source,
 'rollback helper exists':'def _rollback_unready_assignment' in source,
}
for n,ok in checks.items(): print(('PASS ' if ok else 'FAIL ')+n)
raise SystemExit(0 if all(checks.values()) else 1)
