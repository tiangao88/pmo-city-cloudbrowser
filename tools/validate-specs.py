#!/usr/bin/env python3
"""Small deterministic checks for the specification layout."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
errors = []
required = [
    ROOT / "specs" / "README.md",
    ROOT / "specs" / "proposals" / "v0.2" / "README.md",
    ROOT / "specs" / "proposals" / "v0.2" / "85-credential-broker-prd.md",
    ROOT / "specs" / "proposals" / "v0.2" / "86-product-boundaries.md",
    ROOT / "specs" / "proposals" / "v0.2" / "87-broker-security-model.md",
]
for path in required:
    if not path.is_file():
        errors.append(f"missing required specification: {path.relative_to(ROOT)}")
for path in (ROOT / "specs" / "proposals").rglob("*.md"):
    if not re.search(r"(?im)^# ", path.read_text(encoding="utf-8")):
        errors.append(f"missing markdown heading: {path.relative_to(ROOT)}")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print("spec validation: PASS")
