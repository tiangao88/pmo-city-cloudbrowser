"""RED-stage hardening tests for step-15 deployment and runtime boundaries."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.agent_control import AgentControlService, PageState, RestrictedAgentBrowser
from cloudbrowser.browser_slots import BrowserReadiness

ROOT = Path(__file__).resolve().parents[2]


def test_agent_control_is_in_ci_matrix_and_release_manifest() -> None:
    workflow = (ROOT / ".github/workflows/build-images.yml").read_text(encoding="utf-8")
    manifest = (ROOT / "deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml").read_text(
        encoding="utf-8"
    )
    assert "name: agent-control" in workflow
    assert "dockerfile: services/agent-control/Dockerfile" in workflow
    assert "agentControl: 0.2.0-dev1" in manifest
    assert re.search(r"agentControl: sha256:[0-9a-f]{64}", manifest)


def test_agent_control_health_endpoint_is_bounded() -> None:
    browser = RestrictedAgentBrowser(
        readiness=lambda: BrowserReadiness("owner@example.test", "generation-1", True),
        list_pages=lambda: [],
    )
    server = AgentControlService.create_server(
        browser,
        principal_id="owner@example.test",
        browser_id="browser-1",
        generation="generation-1",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=2)
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload == {"status": "ok", "component": "agent-control"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_agent_control_requires_trusted_router_header() -> None:
    browser = RestrictedAgentBrowser(
        readiness=lambda: BrowserReadiness("owner@example.test", "generation-1", True),
        page_info=lambda: PageState("https://example.test", "Example", "Hello"),
    )
    server = AgentControlService.create_server(
        browser,
        principal_id="owner@example.test",
        browser_id="browser-1",
        generation="generation-1",
        shared_secret="trusted-secret-value",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"request_id": "r1", "operation": "page_info", "params": {}}).encode()
        with pytest.raises(HTTPError) as denied:
            urlopen(
                Request(
                    f"http://127.0.0.1:{server.server_port}/agent-control/v1",
                    data=body,
                    method="POST",
                ),
                timeout=2,
            )
        assert denied.value.code == 401
        request = Request(
            f"http://127.0.0.1:{server.server_port}/agent-control/v1",
            data=body,
            method="POST",
            headers={"X-CB-Trusted-Secret": "trusted-secret-value"},
        )
        response = urlopen(request, timeout=2)
        assert json.loads(response.read())["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
