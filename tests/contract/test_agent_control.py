"""RED tests for the step-15 page-state agent-control boundary."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.browser_slots import BrowserReadiness, BrowserUnavailable
from cloudbrowser.agent_control import (
    AgentControlRequest,
    AgentControlService,
    PageState,
    RestrictedAgentBrowser,
)


def _browser() -> RestrictedAgentBrowser:
    calls: list[tuple[str, object]] = []

    def readiness() -> BrowserReadiness:
        return BrowserReadiness("owner@example.test", "generation-1", True)

    def navigate(url: str) -> None:
        calls.append(("navigate", url))

    browser = RestrictedAgentBrowser(
        readiness=readiness,
        list_pages=lambda: [{"tab_id": "tab-1", "url": "https://example.test", "title": "Example"}],
        navigate=navigate,
        click=lambda selector: calls.append(("click", selector)),
        type_text=lambda selector, text: calls.append(("type", (selector, text))),
        page_info=lambda selector=None: PageState(url="https://example.test", title="Example", text="Hello"),
    )
    browser.calls = calls  # type: ignore[attr-defined]
    return browser


def _request(op: str, **params: object) -> AgentControlRequest:
    return AgentControlRequest(
        request_id="request-1",
        principal_id="owner@example.test",
        browser_id="browser-1",
        generation="generation-1",
        operation=op,
        params=params,
    )


def test_page_state_operations_are_bounded_and_owner_bound() -> None:
    browser = _browser()
    service = AgentControlService(browser, principal_id="owner@example.test", browser_id="browser-1", generation="generation-1")

    assert service.handle(_request("page_info")) == {
        "request_id": "request-1",
        "status": "ok",
        "page": {"url": "https://example.test", "title": "Example", "text": "Hello"},
    }
    assert service.handle(_request("navigate", url="https://example.test/next"))["status"] == "ok"
    assert service.handle(_request("click", selector="#submit"))["status"] == "ok"
    assert service.handle(_request("type", selector="#name", text="Alice"))["status"] == "ok"
    assert browser.calls == [
        ("navigate", "https://example.test/next"),
        ("click", "#submit"),
        ("type", ("#name", "Alice")),
    ]


def test_agent_cannot_override_binding_or_use_forbidden_operations() -> None:
    browser = _browser()
    service = AgentControlService(browser, principal_id="owner@example.test", browser_id="browser-1", generation="generation-1")

    altered = AgentControlRequest("request-1", "other@example.test", "browser-1", "generation-1", "page_info", {})
    assert service.handle(altered) == {
        "request_id": "request-1",
        "status": "failed",
        "error_code": "owner_mismatch",
    }
    for operation in ("raw_cdp", "evaluate", "cookies", "storage", "network", "filesystem", "process"):
        result = service.handle(_request(operation))
        assert result["status"] == "unsupported"
        assert result["error_code"] == "capability_denied"
        assert "secret" not in json.dumps(result).lower()


def test_agent_rejects_unsafe_navigation_and_bounds_inputs() -> None:
    browser = _browser()
    service = AgentControlService(browser, principal_id="owner@example.test", browser_id="browser-1", generation="generation-1")
    for params in (
        {"url": "javascript:alert(1)"},
        {"url": "file:///etc/passwd"},
        {"url": "https://example.test/" + "a" * 4096},
    ):
        result = service.handle(_request("navigate", **params))
        assert result["status"] == "failed"
        assert result["error_code"] == "invalid_request"
    result = service.handle(_request("type", selector="#name", text="x" * 4097))
    assert result["status"] == "failed"
    assert result["error_code"] == "invalid_request"


def test_agent_fails_closed_when_browser_readiness_changes() -> None:
    state = {"ready": BrowserReadiness("owner@example.test", "generation-1", True)}
    browser = RestrictedAgentBrowser(
        readiness=lambda: state["ready"],
        list_pages=lambda: [],
        page_info=lambda: PageState("https://example.test", "Example", "Hello"),
    )
    service = AgentControlService(browser, principal_id="owner@example.test", browser_id="browser-1", generation="generation-1")
    state["ready"] = BrowserReadiness("other@example.test", "generation-2", True)
    result = service.handle(_request("page_info"))
    assert result["status"] == "failed"
    assert result["error_code"] == "owner_mismatch"


def test_agent_http_server_never_exposes_raw_cdp_or_sensitive_page_fields() -> None:
    browser = _browser()
    server = AgentControlService.create_server(
        browser,
        principal_id="owner@example.test",
        browser_id="browser-1",
        generation="generation-1",
        shared_secret="test-trusted-secret",
        address=("127.0.0.1", 0),
    )
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/agent-control/v1"
        body = json.dumps({"request_id": "request-1", "operation": "page_info", "params": {}}).encode()
        response = urlopen(Request(url, data=body, method="POST", headers={"X-CB-Trusted-Secret": "test-trusted-secret"}), timeout=2)
        payload = json.loads(response.read())
        assert payload["status"] == "ok"
        assert "cookies" not in json.dumps(payload).lower()
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(url + "/raw-cdp", data=body, method="POST", headers={"X-CB-Trusted-Secret": "test-trusted-secret"}), timeout=2)
        assert denied.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_agent_control_contract_records_the_page_state_boundary() -> None:
    contract = Path(__file__).parents[2] / "specs/contracts/agent-control/v1/contract.md"
    text = contract.read_text()
    for phrase in (
        "page state only",
        "navigate",
        "click",
        "type",
        "owner-bound",
        "raw CDP",
        "network bodies",
        "filesystem",
        "process control",
    ):
        assert phrase in text
