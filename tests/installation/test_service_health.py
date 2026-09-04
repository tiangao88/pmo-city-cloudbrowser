"""Health contracts shared by all runtime service images."""

from pathlib import Path
import subprocess
import sys

from cloudbrowser.health import health_payload


ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("router", "slot-supervisor", "browser", "viewer", "downloads", "credential-broker", "cloudfiles", "identity-link")


def test_health_payload_contains_only_non_sensitive_installation_metadata():
    payload = health_payload(
        component="router",
        instance_id="cloudbrowser-test",
        release_version="0.2.0-dev1",
    )
    assert payload == {
        "status": "ok",
        "component": "router",
        "instance_id": "cloudbrowser-test",
        "release_version": "0.2.0-dev1",
    }
    assert not any(secret in str(payload).lower() for secret in ("password", "token", "cookie"))


def test_manifest_components_include_identity_link_when_present() -> None:
    manifest = (ROOT / "deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml").read_text(encoding="utf-8")
    assert "identityLink: 0.2.0-dev1" in manifest
    assert "identityLink: sha256:REPLACE_BEFORE_IMAGE_PUBLICATION" in manifest


def test_every_service_runtime_module_compiles():
    for service in SERVICES:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", f"services/{service}/entrypoint.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
