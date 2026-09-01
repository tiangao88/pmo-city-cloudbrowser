#!/usr/bin/env python3
"""Validate the bootstrap release manifest without requiring PyYAML."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
example = ROOT / "deploy" / "coolify" / "release-manifest.example.yaml"
text = example.read_text(encoding="utf-8")
required = [
    "apiVersion: cloudbrowser.pmo.city/v1",
    "kind: CloudBrowserRelease",
    "productVersion:",
    "specificationBaseline:",
    "credentialBroker:",
    "imageDigests:",
    "volumePrefix:",
    "rollbackSupported: true",
]
missing = [item for item in required if item not in text]
if missing:
    print("missing manifest fields:", ", ".join(missing))
    raise SystemExit(1)
if "REPLACE_BEFORE_DEPLOY" not in text:
    print("manifest must require explicit image digests before deployment")
    raise SystemExit(1)
print("release-manifest validation: PASS")
