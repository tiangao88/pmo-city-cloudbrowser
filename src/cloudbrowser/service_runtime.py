"""Common startup for the independently deployable service images."""

from __future__ import annotations

import os

from cloudbrowser.deployment import InstanceNamespace
from cloudbrowser.health import serve_health


def run_service(component: str) -> None:
    instance_id = os.environ.get("CB_INSTANCE_ID")
    release_version = os.environ.get("CB_RELEASE_VERSION")
    if not instance_id or not release_version:
        raise SystemExit("CB_INSTANCE_ID and CB_RELEASE_VERSION are required")
    # Validate the installation namespace before opening a listener.
    InstanceNamespace(instance_id)
    try:
        port = int(os.environ.get("CB_PORT", "8080"))
    except ValueError as exc:
        raise SystemExit("CB_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("CB_PORT must be between 1 and 65535")
    serve_health(
        component=component,
        instance_id=instance_id,
        release_version=release_version,
        port=port,
    )
