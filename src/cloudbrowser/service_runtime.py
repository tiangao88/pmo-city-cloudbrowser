"""Shared startup for the independently deployable service images."""

from __future__ import annotations

import os
from pathlib import Path
import time

from cloudbrowser.deployment import InstanceNamespace
from cloudbrowser.health import serve_health


KNOWN_COMPONENTS = {
    "router",
    "slot-supervisor",
    "browser",
    "viewer",
    "agent-control",
    "downloads",
    "credential-broker",
}
_REQUIRED_BINDING_ENV = ("CB_PRINCIPAL_ID", "CB_BROWSER_ID", "CB_BINDING_GENERATION")


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


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
    if component == "viewer":
        from cloudbrowser.viewer import AuthenticatedViewer, ViewerSessionStore, create_viewer_server

        secret = os.environ.get("CB_VIEWER_TOKEN_SECRET")
        if not secret:
            raise SystemExit("CB_VIEWER_TOKEN_SECRET is required")
        try:
            ttl_s = float(os.environ.get("CB_VIEWER_SESSION_TTL_S", "360"))
        except ValueError as exc:
            raise SystemExit("CB_VIEWER_SESSION_TTL_S must be a number") from exc
        store = ViewerSessionStore(clock=time.time)
        viewer = AuthenticatedViewer(store, token_secret=secret.encode("utf-8"), ttl_s=ttl_s)
        server = create_viewer_server(viewer, address=("0.0.0.0", port))
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    if component == "agent-control":
        from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport
        from cloudbrowser.agent_control import AgentControlService
        from cloudbrowser.browser_slots.http_client import HttpJsonClient
        from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport

        principal_id, browser_id, generation = (
            _required_env(name) for name in _REQUIRED_BINDING_ENV
        )
        trusted_secret = _required_env("CB_AGENT_CONTROL_SHARED_SECRET")
        browser_api_url = os.environ.get("CB_BROWSER_API_URL", "http://browser:9230")
        transport = HttpBrowserTransport(
            HttpJsonClient(browser_api_url),
            expected_owner=principal_id,
            expected_generation=generation,
        )
        agent_transport = HttpAgentBrowserTransport(
            transport.client(),
            expected_owner=principal_id,
            expected_generation=generation,
        )
        browser = HttpAgentBrowser(agent_transport)
        server = AgentControlService.create_server(
            browser,
            principal_id=principal_id,
            browser_id=browser_id,
            generation=generation,
            shared_secret=trusted_secret,
            address=("0.0.0.0", port),
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    if component == "downloads":
        from cloudbrowser.downloads.api import create_downloads_server
        from cloudbrowser.downloads.identity import ServerIdentity
        from cloudbrowser.downloads.service import DownloadsService

        principal_id = _required_env("CB_PRINCIPAL_ID")
        browser_id = _required_env("CB_BROWSER_ID")
        generation = _required_env("CB_BINDING_GENERATION")
        shared_secret = _required_env("CB_DOWNLOADS_SHARED_SECRET").encode("utf-8")
        store_root = Path(os.environ.get("CB_DOWNLOADS_ROOT", "/data/downloads"))
        server = create_downloads_server(
            DownloadsService(store_root=store_root),
            server_identity=ServerIdentity(
                component="downloads",
                instance_id=instance_id,
            ),
            trusted_secret=shared_secret,
            address=("0.0.0.0", port),
        )
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    serve_health(component=component, instance_id=instance_id, release_version=release_version, port=port)
