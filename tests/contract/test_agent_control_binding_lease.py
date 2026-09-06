"""RED tests for the authenticated per-request agent binding lease seam."""

from __future__ import annotations

import json
import socket
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.agent_control import AgentControlService, PageState, RestrictedAgentBrowser
from cloudbrowser.browser_slots import BrowserReadiness


_SECRET = "trusted-secret-value"
_BINDING = {
    "X-CB-Principal": "owner@example.test",
    "X-CB-Browser": "browser-1",
    "X-CB-Generation": "generation-1",
}


def _server():
    browser = RestrictedAgentBrowser(
        readiness=lambda: BrowserReadiness("owner@example.test", "generation-1", True),
        page_info=lambda: PageState("https://example.test", "Example", "Hello"),
    )
    return AgentControlService.create_server(
        browser,
        principal_id="owner@example.test",
        browser_id="browser-1",
        generation="generation-1",
        shared_secret=_SECRET,
        address=("127.0.0.1", 0),
    )


def _post(server, *, headers: dict[str, str] | None = None):
    all_headers = {"X-CB-Trusted-Secret": _SECRET}
    if headers:
        all_headers.update(headers)
    body = json.dumps({"request_id": "r1", "operation": "page_info", "params": {}}).encode()
    return urlopen(
        Request(
            f"http://127.0.0.1:{server.server_port}/agent-control/v1",
            data=body,
            method="POST",
            headers=all_headers,
        ),
        timeout=2,
    )


def test_binding_lease_accepts_server_derived_envelope_with_trusted_secret() -> None:
    server = _server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _post(server, headers=_BINDING)
        assert response.status == 200
        assert json.loads(response.read())["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-CB-Principal": "owner@example.test", "X-CB-Browser": "browser-1"},
        {**_BINDING, "X-CB-Generation": ""},
        {**_BINDING, "X-CB-Principal": "other@example.test"},
        {**_BINDING, "X-CB-Browser": "browser-2"},
        {**_BINDING, "X-CB-Generation": "generation-2"},
        {**_BINDING, "X-CB-Browser": "browser/1"},
    ],
)
def test_binding_lease_rejects_absent_malformed_or_mismatched_envelope(headers: dict[str, str]) -> None:
    server = _server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as denied:
            _post(server, headers=headers)
        assert denied.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_binding_lease_rejects_control_character_injection_in_envelope() -> None:
    server = _server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"request_id": "r1", "operation": "page_info", "params": {}}).encode()
        raw = (
            f"POST /agent-control/v1 HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{server.server_port}\r\n"
            f"X-CB-Trusted-Secret: {_SECRET}\r\n"
            f"X-CB-Principal: owner@example.test\x01forged\r\n"
            f"X-CB-Browser: browser-1\r\n"
            f"X-CB-Generation: generation-1\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            "\r\n"
        ).encode("latin-1") + body
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as sock:
            sock.sendall(raw)
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
        assert b" 401 " in response.split(b"\r\n", 1)[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_binding_lease_requires_trusted_secret_alongside_matching_envelope() -> None:
    server = _server()
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
                    headers=_BINDING,
                ),
                timeout=2,
            )
        assert denied.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_binding_lease_keeps_health_unbound_and_page_actions_unchanged() -> None:
    server = _server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health = urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=2)
        assert json.loads(health.read()) == {"status": "ok", "component": "agent-control"}
        response = _post(server, headers=_BINDING)
        assert json.loads(response.read())["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
