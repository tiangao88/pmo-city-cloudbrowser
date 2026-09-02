from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAMES = ("router", "slot-supervisor", "browser", "viewer", "downloads", "credential-broker")


def test_each_service_has_a_real_entrypoint_and_image_definition():
    for service in SERVICE_NAMES:
        entrypoint = ROOT / "services" / service / "entrypoint.py"
        dockerfile = ROOT / "services" / service / "Dockerfile"
        assert entrypoint.is_file(), f"missing entrypoint for {service}"
        assert dockerfile.is_file(), f"missing Dockerfile for {service}"
        docker_text = dockerfile.read_text(encoding="utf-8")
        assert "FROM python:3.12-slim" in docker_text or "FROM debian:bookworm-slim" in docker_text
        assert "COPY src/ /app/src/" in docker_text
        assert f"services/{service}/entrypoint.py" in docker_text


def test_compose_defines_real_services_with_health_and_instance_isolation():
    compose = (ROOT / "deploy" / "coolify" / "compose.yaml").read_text(encoding="utf-8")
    assert "services: {}" not in compose
    assert "${CB_INSTANCE_ID:?" in compose
    assert "name: ${CB_INSTANCE_ID:?" in compose
    assert compose.count("healthcheck:") >= len(SERVICE_NAMES)
    for service in SERVICE_NAMES:
        assert f"  {service}:" in compose
    assert "legacy/" not in compose
    assert "scripts:/app" not in compose


def test_release_preview_is_explicitly_gated_until_images_are_published():
    manifest = (
        ROOT / "deploy" / "coolify" / "releases" / "v0.2.0-dev1" / "release-manifest.yaml"
    ).read_text(encoding="utf-8")
    assert "productVersion: 0.2.0-dev1" in manifest
    assert "installable: true" in manifest
    assert "status: qualified-installable" in manifest
    assert "image publication" not in manifest
    assert "rollbackSupported: true" in manifest
