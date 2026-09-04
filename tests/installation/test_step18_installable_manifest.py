"""Step-18 contracts for the published-image qualification workflow."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml"
QUALIFICATION_DIR = ROOT / "deploy/coolify/image-qualification"
SERVICES = (
    ("router", "router"),
    ("slot-supervisor", "slotSupervisor"),
    ("browser", "browser"),
    ("viewer", "viewer"),
    ("agent-control", "agentControl"),
    ("downloads", "downloads"),
    ("credential-broker", "credentialBroker"),
    ("cloudfiles", "cloudfiles"),
    ("identity-link", "identityLink"),
)


def _manifest() -> str:
    return MANIFEST.read_text(encoding="utf-8")


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


def test_release_has_an_explicit_identity_link_publication_gate() -> None:
    manifest = _manifest()
    assert "productVersion: 0.2.0-dev1" in manifest
    assert "specificationBaseline: v0.2.0" in manifest
    assert "status: qualified-installable" in manifest
    assert "installable: true" in manifest
    assert "identityLink: 0.2.0-dev1" in manifest
    assert "identityLink: sha256:REPLACE_BEFORE_IMAGE_PUBLICATION" in manifest


def test_qualification_records_are_present_and_match_manifest() -> None:
    manifest = _manifest()
    run_url, commit = _provenance(manifest)
    for service, component in SERVICES:
        manifest_match = re.search(
            rf"^    {re.escape(component)}: (sha256:\S+)$", manifest, re.MULTILINE
        )
        assert manifest_match, component
        record = (QUALIFICATION_DIR / f"{service}.md").read_text(encoding="utf-8")
        record_match = re.search(r"^- digest: `([^`]+)`$", record, re.MULTILINE)
        assert record_match, service
        assert record_match.group(1) == manifest_match.group(1), service
        assert "healthcheck" in record.lower(), f"{service}: missing healthcheck"
        assert "provenance" in record.lower(), f"{service}: missing provenance"
        assert f"CI run: `{run_url}`" in record
        assert f"source commit `{commit}`" in record
        if service == "identity-link":
            assert "- status: pending" in record
            continue
        assert "- status: passed" in record, service
        assert "configured user: `cloudbrowser`" in record
        assert "runtime endpoint: passed" in record


def test_both_compose_variants_require_the_viewer_secret() -> None:
    marker = "CB_VIEWER_TOKEN_SECRET: ${CB_VIEWER_TOKEN_SECRET:?CB_VIEWER_TOKEN_SECRET is required}"
    for relative_path in ("deploy/coolify/compose.yaml", "deploy/coolify/compose.coolify.yaml"):
        compose = (ROOT / relative_path).read_text(encoding="utf-8")
        viewer_section = compose.split("  viewer:\n", 1)[1].split("\n  downloads:", 1)[0]
        assert marker in viewer_section
