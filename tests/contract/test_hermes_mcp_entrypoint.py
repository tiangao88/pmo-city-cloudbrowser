"""Contract tests for the supported Hermes stdio MCP entrypoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from email.message import Message

from cloudbrowser.hermes_mcp import CloudBrowserHttpClient, HermesMcpServer


class _Response:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode()
        self.headers = Message()
        self.headers["Content-Type"] = "application/json"

    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


class _CloudBrowserStub:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def open(self, request, timeout: float):  # noqa: ANN001
        path = request.full_url.removeprefix("https://cloudbrowser.example.test")
        body = json.loads(request.data) if request.data else {}
        self.calls.append(
            {
                "path": path,
                "headers": {key.lower(): value for key, value in request.header_items()},
                "body": body,
            }
        )
        if path == "/ui/session/join":
            payload = {"request_id": "server", "status": "offered", "slot_id": "slot-1"}
        elif path == "/ui/session/activate":
            payload = {"request_id": "server", "status": "active", "slot_id": "slot-1"}
        elif path == "/ui/agent/tab_open":
            payload = {
                "request_id": "server",
                "status": "ok",
                "page": {"tab_id": "tab-real", "url": "https://app.example.test/", "title": "App"},
            }
        elif path == "/ui/credential/login":
            payload = {"request_id": "server", "status": "authenticated"}
        else:
            payload = {"request_id": "server", "status": "ok"}
        return _Response(payload)


def _rpc(server: HermesMcpServer, method: str, params: dict | None = None, rpc_id: int = 1):
    request = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        request["params"] = params
    response = server.handle_rpc(request)
    assert response is not None
    return response


def test_initialize_and_tools_list_expose_only_bounded_cloudbrowser_operations() -> None:
    server = HermesMcpServer(client=None)
    initialized = _rpc(
        server,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    )
    assert initialized["result"]["protocolVersion"] == "2025-06-18"
    listed = _rpc(server, "tools/list", {})
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {
        "cloudbrowser_start",
        "cloudbrowser_tabs_list",
        "cloudbrowser_tab_open",
        "cloudbrowser_navigate",
        "cloudbrowser_click",
        "cloudbrowser_type",
        "cloudbrowser_page_info",
        "cloudbrowser_credential_login",
    }
    assert not names & {"raw_cdp", "evaluate", "cookies", "storage", "network", "filesystem", "process"}


def test_tool_calls_use_authenticated_viewer_routes_and_never_send_owner_headers() -> None:
    stub = _CloudBrowserStub()
    client = CloudBrowserHttpClient(
        base_url="https://cloudbrowser.example.test",
        authorization="Basic synthetic-profile-secret",
        request_id_factory=lambda: "mcp-request",
        opener=stub,
    )
    server = HermesMcpServer(client=client)
    started = _rpc(server, "tools/call", {"name": "cloudbrowser_start", "arguments": {}})
    assert started["result"]["structuredContent"]["status"] == "active"
    opened = _rpc(
        server,
        "tools/call",
        {"name": "cloudbrowser_tab_open", "arguments": {"url": "https://app.example.test/"}},
    )
    assert opened["result"]["structuredContent"]["page"]["tab_id"] == "tab-real"
    login = _rpc(
        server,
        "tools/call",
        {
            "name": "cloudbrowser_credential_login",
            "arguments": {"site_id": "declared-app", "target_tab_id": "tab-real"},
        },
    )
    assert login["result"]["structuredContent"] == {
        "request_id": "server",
        "status": "authenticated",
    }

    assert [call["path"] for call in stub.calls] == [
        "/ui/session/join",
        "/ui/session/activate",
        "/ui/agent/tab_open",
        "/ui/credential/login",
    ]
    for call in stub.calls:
        headers = call["headers"]
        assert headers["authorization"] == "Basic synthetic-profile-secret"
        assert headers["x-cb-request-id"] == "mcp-request"
        assert not ({"remote-sub", "remote-user", "x-cb-principal", "x-cb-browser"} & set(headers))
    assert stub.calls[2]["body"] == {"params": {"url": "https://app.example.test/"}}
    assert stub.calls[3]["body"] == {
        "request_id": "mcp-request",
        "site_id": "declared-app",
        "target_tab_id": "tab-real",
    }


def test_notifications_do_not_produce_json_rpc_responses() -> None:
    server = HermesMcpServer(client=None)
    assert server.handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_installed_module_speaks_newline_delimited_stdio_mcp() -> None:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "hermes-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    env = dict(os.environ)
    env.update(
        {
            "CB_CLOUDBROWSER_URL": "https://cloudbrowser.example.test",
            "CB_CLOUDBROWSER_AUTHORIZATION": "Bearer subprocess-test-token",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "cloudbrowser.hermes_mcp"],
        input="".join(json.dumps(message) + "\n" for message in messages),
        text=True,
        capture_output=True,
        timeout=5,
        env=env,
        check=True,
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2]
    assert len(responses[1]["result"]["tools"]) == 8
    assert "subprocess-test-token" not in result.stdout
    assert result.stderr == ""
