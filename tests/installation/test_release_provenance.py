"""Regression coverage for the final release provenance correction."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml"
QUALIFICATION_DIR = ROOT / "deploy/coolify/image-qualification"


def _provenance(manifest: str) -> tuple[str, str]:
    run_match = re.search(
        r"^    run: (https://github\.com/[^\s]+/actions/runs/[0-9]+)$",
        manifest,
        re.MULTILINE,
    )
    commit_match = re.search(r"^    commit: ([0-9a-f]{40})$", manifest, re.MULTILINE)
    assert run_match
    assert commit_match
    return run_match.group(1), commit_match.group(1)


def test_manifest_provenance_is_not_stale_or_placeholder() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    run_url, commit = _provenance(manifest)
    assert run_url.endswith("/actions/runs/33827177104")
    assert commit == "1d9ea90750d6ee4a3e39071fd14650891f06115e"
    assert "QUALIFICATION_RUN_REQUIRED" not in manifest
    assert "QUALIFICATION_COMMIT_REQUIRED" not in manifest
    assert "REPLACE_BEFORE_IMAGE_PUBLICATION" not in manifest


def test_qualification_records_share_manifest_provenance_and_digests() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    run_url, commit = _provenance(manifest)
    components = {
        "router": "router",
        "slot-supervisor": "slotSupervisor",
        "browser": "browser",
        "viewer": "viewer",
        "agent-control": "agentControl",
        "downloads": "downloads",
        "credential-broker": "credentialBroker",
        "cloudfiles": "cloudfiles",
    }
    for service, component in components.items():
        manifest_digest = re.search(
            rf"^    {re.escape(component)}: (sha256:[0-9a-f]{{64}})$", manifest, re.MULTILINE
        )
        assert manifest_digest, component
        record = (QUALIFICATION_DIR / f"{service}.md").read_text(encoding="utf-8")
        assert f"- digest: `{manifest_digest.group(1)}`" in record
        assert f"- CI run: `{run_url}`" in record
        assert f"source commit `{commit}`" in record
