"""Step-18 contracts for an installable, digest-pinned release manifest."""

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
)
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _manifest() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def test_release_is_installable_only_with_real_pinned_digests() -> None:
    manifest = _manifest()
    assert "productVersion: 0.2.0-dev1" in manifest
    assert "specificationBaseline: v0.2.0" in manifest
    assert "status: qualified-installable" in manifest
    assert "installable: true" in manifest
    assert "REPLACE_BEFORE_IMAGE_PUBLICATION" not in manifest
    for _, component in SERVICES:
        match = re.search(rf"^    {re.escape(component)}: (sha256:\S+)$", manifest, re.MULTILINE)
        assert match, component
        assert DIGEST_RE.fullmatch(match.group(1)), component


def test_qualification_records_are_passed_and_match_manifest_digests() -> None:
    manifest = _manifest()
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
        assert "CI run: `https://github.com/tiangao88/pmo-city-cloudbrowser/actions/runs/33670797654`" in record
        assert re.search(r"^- status: passed$", record, re.MULTILINE), service
        assert "configured user: `cloudbrowser`" in record
        assert "runtime endpoint: passed" in record


def test_both_compose_variants_require_the_viewer_secret() -> None:
    marker = "CB_VIEWER_TOKEN_SECRET: ${CB_VIEWER_TOKEN_SECRET:?CB_VIEWER_TOKEN_SECRET is required}"
    for relative_path in ("deploy/coolify/compose.yaml", "deploy/coolify/compose.coolify.yaml"):
        compose = (ROOT / relative_path).read_text(encoding="utf-8")
        viewer_section = compose.split("  viewer:", 1)[1].split("\n  downloads:", 1)[0]
        assert marker in viewer_section, relative_path


def test_coolify_compose_uses_the_same_immutable_digests() -> None:
    manifest = _manifest()
    compose = (ROOT / "deploy/coolify/compose.coolify.yaml").read_text(encoding="utf-8")
    for service, component in SERVICES:
        digest = re.search(
            rf"^    {re.escape(component)}: (sha256:\S+)$", manifest, re.MULTILINE
        ).group(1)
        image_match = re.search(
            rf"^    image: ghcr.io/tiangao88/pmo-city-cloudbrowser/{re.escape(service)}@({re.escape(digest)})$",
            compose,
            re.MULTILINE,
        )
        assert image_match, service
