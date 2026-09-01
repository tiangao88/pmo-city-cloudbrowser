#!/usr/bin/env python3
"""Reject common secret/artifact names and obvious credential assignments."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ignored = {".git", ".venv", "__pycache__"}
name_pattern = re.compile(
    r"(^|\\.)(env|pem|key|p12|pfx|kdbx|sqlite|sqlite3|db|log|har|trace|pcap)$", re.I
)
secret_pattern = re.compile(
    r"(?i)(password|token|secret|refresh[_-]?token|otp[_-]?seed)\\s*[:=]\\s*"
    r"[^$<{`'\\\"]{8,}"
)
errors = []
for path in ROOT.rglob("*"):
    if not path.is_file() or any(part in ignored for part in path.parts):
        continue
    if name_pattern.search(path.name) and path.name != ".env.example":
        errors.append(f"sensitive filename: {path.relative_to(ROOT)}")
        continue
    if path.suffix.lower() in {".md", ".py", ".sh", ".yaml", ".yml", ".toml", ".json", ".conf"}:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if secret_pattern.search(text):
            errors.append(f"possible inline secret assignment: {path.relative_to(ROOT)}")
if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print("sensitive-file validation: PASS")
