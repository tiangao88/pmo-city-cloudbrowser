"""Step-17 contracts for the published-image qualification workflow."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICES = (
    "router",
    "slot-supervisor",
    "browser",
    "viewer",
    "agent-control",
    "downloads",
    "credential-broker",
    "cloudfiles",
    "identity-link",
)


def test_build_workflow_matrix_covers_every_runtime_service() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-images.yml").read_text(encoding="utf-8")
    for service in SERVICES:
        assert f"name: {service}" in workflow
        assert f"dockerfile: services/{service}/Dockerfile" in workflow
    assert "provenance: true" in workflow
    assert "sbom: true" in workflow
    assert "packages: write" in workflow


def test_build_workflow_validates_inputs_before_publishing() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-images.yml").read_text(encoding="utf-8")
    assert "uses: astral-sh/setup-uv@v5" in workflow
    assert "uv sync --dev" in workflow
    assert "uv run make check" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "needs: validate" in workflow


def test_build_workflow_qualifies_each_published_image() -> None:
    workflow = (ROOT / ".github" / "workflows" / "build-images.yml").read_text(encoding="utf-8")
    assert "id: build" in workflow
    assert "docker pull" in workflow
    assert "docker image inspect" in workflow
    assert "State.Health.Status" in workflow
    assert "Config.User" in workflow
    assert "docker exec" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert "steps.build.outputs.digest" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow


def test_every_image_has_a_qualification_record_template() -> None:
    directory = ROOT / "deploy" / "coolify" / "image-qualification"
    for service in SERVICES:
        record = directory / f"{service}.md"
        assert record.is_file(), service
        text = record.read_text(encoding="utf-8")
        for marker in ("image:", "digest:", "non-root", "healthcheck", "provenance", "status:"):
            assert marker in text.lower(), f"{service}: missing {marker}"


def test_release_manifest_lists_the_same_seven_image_components() -> None:
    manifest = (
        ROOT / "deploy" / "coolify" / "releases" / "v0.2.0-dev1" / "release-manifest.yaml"
    ).read_text(encoding="utf-8")
    component_names = {
        "router:",
        "slotSupervisor:",
        "browser:",
        "viewer:",
        "agentControl:",
        "downloads:",
        "credentialBroker:",
        "cloudfiles:",
    }
    image_section = manifest.split("  imageDigests:", 1)[1]
    for name in component_names:
        assert name in manifest
        assert name in image_section
    assert "installable: true" in manifest
    assert "identityLink: sha256:" in manifest
