#!/usr/bin/env python3
"""Validate the bootstrap release manifest without requiring PyYAML."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
example = ROOT / "deploy" / "coolify" / "release-manifest.example.yaml"
text = example.read_text(encoding="utf-8")
required = [
    "apiVersion: cloudbrowser.pmo.city/v1",
    "kind: CloudBrowserRelease",
    "productVersion:",
    "specificationBaseline:",
    "credentialBroker:",
    "cloudfiles:",
    "identityLink:",
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

release = ROOT / "deploy" / "coolify" / "releases" / "v0.2.0-dev1" / "release-manifest.yaml"
release_text = release.read_text(encoding="utf-8")
for marker in (
    "status: image-qualified-ready-for-deployment",
    "installable: true",
    "sourceState: qualified",
    "imageState: qualified",
):
    if marker not in release_text:
        print(f"release manifest missing {marker}")
        raise SystemExit(1)
qualification_run = re.search(
    r"^    run: (https://github\.com/[^\s]+/actions/runs/[0-9]+)$",
    release_text,
    re.MULTILINE,
)
qualification_commit = re.search(
    r"^    commit: ([0-9a-f]{40})$", release_text, re.MULTILINE
)
if not qualification_run:
    print("release manifest is missing the qualification run")
    raise SystemExit(1)
if not qualification_commit:
    print("release manifest is missing the qualification commit")
    raise SystemExit(1)
for component in (
    "router",
    "slotSupervisor",
    "browser",
    "viewer",
    "agentControl",
    "downloads",
    "credentialBroker",
    "cloudfiles",
):
    match = re.search(rf"^    {component}: (sha256:\S+)$", release_text, re.MULTILINE)
    if not match or not re.fullmatch(r"sha256:[0-9a-f]{64}", match.group(1)):
        print(f"release component lacks an immutable digest: {component}")
        raise SystemExit(1)
identity_link = re.search(r"^    identityLink: (sha256:\S+)$", release_text, re.MULTILINE)
if not identity_link or not re.fullmatch(r"sha256:[0-9a-f]{64}", identity_link.group(1)):
    print("release component lacks an immutable digest: identityLink")
    raise SystemExit(1)
print("release-manifest validation: PASS")
