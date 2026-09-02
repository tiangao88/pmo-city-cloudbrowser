#!/usr/bin/env python3
"""Validate the installability development scaffold without PyYAML."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("router", "slot-supervisor", "browser", "viewer", "agent-control", "downloads", "credential-broker")
COMPOSE = ROOT / "deploy" / "coolify" / "compose.yaml"
MANIFEST = ROOT / "deploy" / "coolify" / "releases" / "v0.2.0-dev1" / "release-manifest.yaml"


def fail(message: str) -> None:
    print(f"installation validation: FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    if "services: {}" in compose:
        fail("Compose bundle is empty")
    for marker in (
        "${CB_INSTANCE_ID:?CB_INSTANCE_ID is required}",
        "name: ${CB_INSTANCE_ID:?CB_INSTANCE_ID is required}-network",
        "name: ${CB_INSTANCE_ID:?CB_INSTANCE_ID is required}-router-state",
    ):
        if marker not in compose:
            fail(f"missing isolation marker: {marker}")
    if "legacy/" in compose or "scripts:/app" in compose:
        fail("Compose bundle imports legacy runtime paths")
    if compose.count("healthcheck:") < len(SERVICES):
        fail("every service must define a healthcheck")
    for service in SERVICES:
        entrypoint = ROOT / "services" / service / "entrypoint.py"
        dockerfile = ROOT / "services" / service / "Dockerfile"
        if not entrypoint.is_file() or not dockerfile.is_file():
            fail(f"missing image inputs for {service}")
        docker_text = dockerfile.read_text(encoding="utf-8")
        for marker in (
            "COPY src/ /app/src/",
            f"COPY services/{service}/entrypoint.py",
            "HEALTHCHECK",
        ):
            if marker not in docker_text:
                fail(f"{service} Dockerfile missing {marker}")
        if not ("FROM python:3.12-slim" in docker_text or "FROM debian:bookworm-slim" in docker_text):
            fail(f"{service} Dockerfile missing supported base image")

    manifest = MANIFEST.read_text(encoding="utf-8")
    for marker in (
        "apiVersion: cloudbrowser.pmo.city/v1",
        "kind: CloudBrowserRelease",
        "productVersion: 0.2.0-dev1",
        "specificationBaseline: v0.2.0",
        "installable: false",
        "image publication",
        "rollbackSupported: true",
    ):
        if marker not in manifest:
            fail(f"release manifest missing {marker}")
    print("installation validation: PASS")


if __name__ == "__main__":
    main()
