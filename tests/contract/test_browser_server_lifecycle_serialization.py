"""Browser HTTP operations serialize with Chrome lifecycle transitions."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.browser_slots.transport import BrowserReadiness


TRUSTED_SECRET = "lifecycle-test-secret-0123456789"
NEW_BINDING = {
    "principal_id": "principal-new",
    "profile_id": "profile-new",
    "browser_id": "browser-1",
    "generation": "generation-new",
}


class _Process:
    def __init__(self) -> None:
        self.state = "stopped"
        self.start_entered = threading.Event()
        self.release_start = threading.Event()
        self.rebind_entered = threading.Event()
        self.release_rebind = threading.Event()

    def start(self) -> bool:
        self.state = "starting"
        self.start_entered.set()
        assert self.release_start.wait(2)
        self.state = "ready"
        return True

    def stop(self) -> None:
        self.state = "stopped"

    def readiness(self) -> bool:
        return self.state == "ready"

    def rebind(
        self,
        owner: str,
        generation: str,
        *,
        profile_id: str,
        browser_id: str,
    ) -> None:
        del owner, generation, profile_id, browser_id
        self.rebind_entered.set()
        assert self.release_rebind.wait(2)
        self.state = "stopped"


class _Chrome:
    def __init__(self, operation_entered: threading.Event) -> None:
        self._operation_entered = operation_entered

    def json_request(self, path: str, *, method: str = "GET") -> object:
        del method
        if path == "/json/list":
            self._operation_entered.set()
            return []
        raise AssertionError(f"unexpected Chrome request: {path}")


class _Adapter:
    def __init__(self, process: _Process) -> None:
        self._process = process
        self.operation_entered: dict[str, threading.Event] = {
            name: threading.Event()
            for name in (
                "readiness",
                "list_page_urls",
                "agent_pages",
                "open_page",
                "close_empty_pages",
                "page_info",
                "navigate",
                "click",
                "type_text",
            )
        }
        self.chrome = _Chrome(self.operation_entered["agent_pages"])
        self.owner = "principal-old"
        self.generation = "generation-old"
        self.blocked_operation: str | None = None
        self.release_blocked_operation = threading.Event()

    def start(self) -> bool:
        return self._process.start()

    def stop(self) -> None:
        self._process.stop()

    def readiness(self) -> BrowserReadiness:
        self._enter("readiness")
        return BrowserReadiness(self.owner, self.generation, self._process.state == "ready")

    def list_page_urls(self) -> list[str]:
        self._enter("list_page_urls")
        return []

    def agent_pages(self) -> list[dict[str, str]]:
        self._enter("agent_pages")
        return [{"tab_id": "tab-1", "url": "https://example.test", "title": "Example"}]

    def open_page(self, url: str) -> None:
        del url
        self._enter("open_page")

    def close_empty_pages(self) -> None:
        self._enter("close_empty_pages")

    def page_info(self, target_tab_id: str, selector: str | None = None) -> dict[str, str]:
        del target_tab_id, selector
        self._enter("page_info")
        return {"url": "https://example.test", "title": "Example", "text": ""}

    def navigate(self, target_tab_id: str, url: str) -> None:
        del target_tab_id, url
        self._enter("navigate")

    def click(self, target_tab_id: str, selector: str) -> None:
        del target_tab_id, selector
        self._enter("click")

    def type_text(self, target_tab_id: str, selector: str, text: str) -> None:
        del target_tab_id, selector, text
        self._enter("type_text")

    def rebind(
        self,
        owner: str,
        generation: str,
        *,
        profile_id: str,
        browser_id: str,
    ) -> None:
        self.owner = owner
        self.generation = generation
        del profile_id, browser_id

    def _enter(self, operation: str) -> None:
        self.operation_entered[operation].set()
        if self.blocked_operation == operation:
            assert self.release_blocked_operation.wait(2)


def _server(process: _Process, adapter: _Adapter):
    return create_browser_server(
        adapter,  # type: ignore[arg-type]
        process,  # type: ignore[arg-type]
        instance_id="test-instance",
        release_version="test-release",
        address=("127.0.0.1", 0),
    )


def _request(
    server: Any,
    method: str,
    path: str,
    *,
    body: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, object]:
    data = body.encode("utf-8") if body is not None else None
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}",
        data=data,
        method=method,
        headers=headers or {},
    )
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))
    with response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _run_server(process: _Process, adapter: _Adapter):
    server = _server(process, adapter)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _close_server(server: Any, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_browser_deadline_is_not_renewed_after_lifecycle_queue_wait() -> None:
    """A queued credential submit expires from receipt, not lock acquisition."""
    class Basic:
        called = False

        def submit(self, *_args: object, deadline=None, **_kwargs: object) -> None:
            assert deadline is not None
            deadline.check()
            self.called = True

    now = [100.0]
    process = _Process()
    adapter = _Adapter(process)
    basic = Basic()
    server = create_browser_server(
        adapter,  # type: ignore[arg-type]
        process,  # type: ignore[arg-type]
        instance_id="test-instance",
        release_version="test-release",
        address=("127.0.0.1", 0),
        basic_auth=basic,
        broker_submit_secret=TRUSTED_SECRET,
        monotonic_clock=lambda: now[0],
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    outcomes: dict[str, tuple[int, object]] = {}
    try:
        starter = threading.Thread(
            target=lambda: outcomes.setdefault("start", _request(server, "POST", "/browser/start"))
        )
        starter.start()
        assert process.start_entered.wait(1)

        payload = json.dumps(
            {
                "origin": "https://basic.example.test",
                "username": "alice",
                "password": "secret",
                "target_id": "target-1",
                "success_path": "/home",
            }
        )
        submitter = threading.Thread(
            target=lambda: outcomes.setdefault(
                "submit",
                _request(
                    server,
                    "POST",
                    "/broker/basic/submit",
                    body=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-CB-Broker-Secret": TRUSTED_SECRET,
                        "X-CB-Broker-Deadline-S": "0.100000",
                    },
                ),
            )
        )
        submitter.start()
        time.sleep(0.05)
        now[0] = 100.2
        process.release_start.set()
        starter.join(timeout=2)
        submitter.join(timeout=2)

        assert not starter.is_alive()
        assert not submitter.is_alive()
        assert outcomes["submit"] == (
            504,
            {"ok": False, "error_code": "deadline_exceeded"},
        )
        assert basic.called is False
    finally:
        process.release_start.set()
        _close_server(server, thread)


@pytest.mark.parametrize(
    ("method", "path", "body", "operation"),
    [
        ("GET", "/browser/readiness", None, "readiness"),
        ("GET", "/browser/pages", None, "list_page_urls"),
        ("POST", "/browser/pages/open", "https://example.test/new", "open_page"),
        ("POST", "/browser/pages/close-empty", None, "close_empty_pages"),
        ("GET", "/agent/pages", None, "agent_pages"),
        ("GET", "/agent/pages/info?target_tab_id=tab-1", None, "page_info"),
        (
            "POST",
            "/agent/pages/navigate",
            json.dumps({"target_tab_id": "tab-1", "value": "https://example.test/new"}),
            "navigate",
        ),
        (
            "POST",
            "/agent/pages/click",
            json.dumps({"target_tab_id": "tab-1", "value": "#submit"}),
            "click",
        ),
        (
            "POST",
            "/agent/pages/type",
            json.dumps({"target_tab_id": "tab-1", "selector": "#name", "text": "Alice"}),
            "type_text",
        ),
    ],
)
def test_browser_http_operation_waits_for_start(
    method: str,
    path: str,
    body: str | None,
    operation: str,
) -> None:
    """No Chrome-facing request may enter while start owns the lifecycle gate."""
    process = _Process()
    adapter = _Adapter(process)
    server, thread = _run_server(process, adapter)
    outcomes: dict[str, tuple[int, object]] = {}
    try:
        starter = threading.Thread(
            target=lambda: outcomes.setdefault("start", _request(server, "POST", "/browser/start"))
        )
        starter.start()
        assert process.start_entered.wait(1)

        contender = threading.Thread(
            target=lambda: outcomes.setdefault("contender", _request(server, method, path, body=body))
        )
        contender.start()
        assert not adapter.operation_entered[operation].wait(0.2), (
            f"{operation} entered while browser start was in flight"
        )

        process.release_start.set()
        starter.join(timeout=2)
        contender.join(timeout=2)
        assert not starter.is_alive()
        assert not contender.is_alive()
        assert outcomes["start"] == (200, {"ok": True})
        assert outcomes["contender"][0] in {200, 503}
    finally:
        process.release_start.set()
        adapter.release_blocked_operation.set()
        _close_server(server, thread)


def test_browser_http_operations_wait_for_binding_push() -> None:
    """Readiness and page listing cannot observe a half-applied binding."""
    for method, path, operation in (
        ("GET", "/browser/readiness", "readiness"),
        ("GET", "/browser/pages", "list_page_urls"),
    ):
        process = _Process()
        adapter = _Adapter(process)
        server, thread = _run_server(process, adapter)
        outcomes: dict[str, tuple[int, object]] = {}
        original_secret = os.environ.get("CB_ROUTER_SHARED_SECRET")
        os.environ["CB_ROUTER_SHARED_SECRET"] = TRUSTED_SECRET
        try:
            binding_request = threading.Thread(
                target=lambda: outcomes.setdefault(
                    "binding",
                    _request(
                        server,
                        "POST",
                        "/browser/binding",
                        body=json.dumps(NEW_BINDING),
                        headers={"X-CB-Trusted-Secret": TRUSTED_SECRET},
                    ),
                )
            )
            binding_request.start()
            assert process.rebind_entered.wait(1)

            contender = threading.Thread(
                target=lambda: outcomes.setdefault("contender", _request(server, method, path))
            )
            contender.start()
            assert not adapter.operation_entered[operation].wait(0.2)

            process.release_rebind.set()
            binding_request.join(timeout=2)
            contender.join(timeout=2)
            assert not binding_request.is_alive()
            assert not contender.is_alive()
            assert outcomes["binding"] == (200, {"ok": True})
            assert outcomes["contender"][0] in {200, 503}
        finally:
            process.release_rebind.set()
            if original_secret is None:
                os.environ.pop("CB_ROUTER_SHARED_SECRET", None)
            else:
                os.environ["CB_ROUTER_SHARED_SECRET"] = original_secret
            _close_server(server, thread)


def test_page_operations_hold_lifecycle_gate_against_binding_push(monkeypatch) -> None:
    """A page mutation must finish before a new binding can be adopted."""
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", TRUSTED_SECRET)
    for operation, path, body in (
        ("open_page", "/browser/pages/open", "https://example.test/new"),
        ("close_empty_pages", "/browser/pages/close-empty", None),
    ):
        process = _Process()
        adapter = _Adapter(process)
        adapter.blocked_operation = operation
        server, thread = _run_server(process, adapter)
        outcomes: dict[str, tuple[int, object]] = {}
        try:
            page_request = threading.Thread(
                target=lambda: outcomes.setdefault(
                    "page", _request(server, "POST", path, body=body)
                )
            )
            page_request.start()
            assert adapter.operation_entered[operation].wait(1)

            binding_request = threading.Thread(
                target=lambda: outcomes.setdefault(
                    "binding",
                    _request(
                        server,
                        "POST",
                        "/browser/binding",
                        body=json.dumps(NEW_BINDING),
                        headers={"X-CB-Trusted-Secret": TRUSTED_SECRET},
                    ),
                )
            )
            binding_request.start()
            assert not process.rebind_entered.wait(0.2)

            adapter.release_blocked_operation.set()
            page_request.join(timeout=2)
            process.release_rebind.set()
            binding_request.join(timeout=2)
            assert not page_request.is_alive()
            assert not binding_request.is_alive()
            assert outcomes["page"] == (200, {"ok": True})
            assert outcomes["binding"] == (200, {"ok": True})
        finally:
            adapter.release_blocked_operation.set()
            process.release_rebind.set()
            _close_server(server, thread)
