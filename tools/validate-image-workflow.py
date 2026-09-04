"""Validate the image publication workflow's static qualification contract."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-images.yml"
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


def fail(message: str) -> None:
    print(f"image-workflow validation: FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        "uses: astral-sh/setup-uv@v5",
        "uv sync --dev",
        "uv run make check",
        "needs: validate",
        "docker/setup-buildx-action@v3",
        "docker/login-action@v3",
        "docker/metadata-action@v5",
        "docker/build-push-action@v6",
        "provenance: true",
        "sbom: true",
        "docker pull",
        "docker image inspect",
        "docker buildx imagetools inspect",
        "State.Health.Status",
        "Config.User",
        "docker exec",
        "curl --fail",
        "actions/upload-artifact@v4",
        "GITHUB_STEP_SUMMARY",
    )
    for marker in required:
        if marker not in text:
            fail(f"missing workflow marker: {marker}")
    if text.count("dockerfile: services/") != len(SERVICES):
        fail("build matrix does not contain exactly one Dockerfile per service")
    for service in SERVICES:
        if f"name: {service}" not in text:
            fail(f"missing matrix service: {service}")
        if not (ROOT / "services" / service / "Dockerfile").is_file():
            fail(f"missing Dockerfile: {service}")
        if not (ROOT / "services" / service / "entrypoint.py").is_file():
            fail(f"missing entrypoint: {service}")
        if not (ROOT / "deploy" / "coolify" / "image-qualification" / f"{service}.md").is_file():
            fail(f"missing qualification template: {service}")

    manifest = (ROOT / "deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml").read_text(
        encoding="utf-8"
    )
    if "installable: true" not in manifest:
        fail("Step-18 release is not installable")
    if manifest.count("installable: true") != 1:
        fail("release manifest must declare installable exactly once")
    if "status: qualified-installable" not in manifest:
        fail("release manifest is missing qualified status")
    if "identityLink" not in manifest:
        fail("release manifest lacks identityLink component")
    identity_link_match = re.search(
        r"^    identityLink: (sha256:\S+)$", manifest, re.MULTILINE
    )
    if not identity_link_match or "REPLACE_BEFORE_IMAGE_PUBLICATION" not in identity_link_match.group(1):
        fail("identityLink digest must remain gated until CI publication")
    print("image-workflow validation: PASS")


if __name__ == "__main__":
    main()
