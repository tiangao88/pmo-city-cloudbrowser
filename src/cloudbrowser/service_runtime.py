"""Shared startup for the independently deployable service images."""

from __future__ import annotations

import os
from pathlib import Path

from cloudbrowser.deployment import InstanceNamespace
from cloudbrowser.health import serve_health


KNOWN_COMPONENTS = {"router", "slot-supervisor", "browser", "viewer", "downloads", "credential-broker"}


def run_service(component: str) -> None:
    instance_id = os.environ.get("CB_INSTANCE_ID")
    release_version = os.environ.get("CB_RELEASE_VERSION")
    if not instance_id or not release_version:
        raise SystemExit("CB_INSTANCE_ID and CB_RELEASE_VERSION are required")
    InstanceNamespace(instance_id)
    if component not in KNOWN_COMPONENTS:
        raise SystemExit("unknown service component")
    try:
        port = int(os.environ.get("CB_PORT", "8080"))
    except ValueError as exc:
        raise SystemExit("CB_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("CB_PORT must be between 1 and 65535")
    if component == "browser":
        from cloudbrowser.browser_service import run_browser_service

        run_browser_service()
        return
    if component == "slot-supervisor":
        from cloudbrowser.browser_slots import BrowserBinding, OwnerBoundLifecycle, SlotSupervisor
        from cloudbrowser.browser_slots.http_client import HttpJsonClient
        from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
        from cloudbrowser.router.control_api import ControlApi, create_control_server

        binding = BrowserBinding(
            profile_id=os.environ.get("CB_PROFILE_ID", "profile-unassigned"),
            principal_id=os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned"),
            browser_id=os.environ.get("CB_BROWSER_ID", "browser-unassigned"),
            generation=os.environ.get("CB_BINDING_GENERATION", "generation-0"),
        )
        browser_api_url = os.environ.get("CB_BROWSER_API_URL", "http://browser:9230")
        transport = HttpBrowserTransport(
            HttpJsonClient(browser_api_url),
            expected_owner=binding.principal_id,
            expected_generation=binding.generation,
        )
        lifecycle = OwnerBoundLifecycle(
            binding, Path(os.environ.get("CB_SNAPSHOT_PATH", "/data/state/tabs.json"))
        )
        server = create_control_server(
            ControlApi(SlotSupervisor(lifecycle, transport), binding),
            address=("0.0.0.0", port),
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    serve_health(
        component=component,
        instance_id=instance_id,
        release_version=release_version,
        port=port,
    )
