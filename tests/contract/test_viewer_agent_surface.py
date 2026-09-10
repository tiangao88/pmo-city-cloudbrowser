"""Viewer agent surface: the UI shell relays allowlisted page actions.

The viewer frontend milestone turns the static shell into the interactive
surface. The shell auto-joins the router queue, polls status, activates an
offered session, and then drives the caller's assigned slot through the
router's allowlisted agent operations only (navigate/click/type/page_info/
tabs_list). The same fail-closed rules as every other surface apply:

- identity is resolved through the identity-link client only; unresolved or
  forged identity fails closed (401) before the router is contacted;
- the viewer refuses forbidden/unknown operations locally and never forwards
  caller credentials or raw edge headers downstream;
- params are bounded before relay (URL scheme/host caps, selector/text caps);
- responses stay bounded router envelopes; no principal IDs, binding tuples,
  or secret material ever reach the UI.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.viewer import create_viewer_server
from cloudbrowser.viewer.session_surface import RouterHttpClient, ViewerSessionSurface

_EDGE_HEADERS = {
    "Remote-Sub": "oidc-sub-1",
    "Remote-User": "jdoe",
    "Remote-Email": "jdoe@example.com",
    "Remote-Groups": "PMOC_Users",
}


class _FakeIdentityLinkClient:
    def __init__(self, principal: str | None = "pmo-owner-001") -> None:
        self._principal = principal

    def resolve(self, identity: object) -> str | None:
        return self._principal


class _FakeRouterClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.agent_response: dict[str, object] = {
            "request_id": "ui-req-1",
            "status": "ok",
            "page": {"url": "https://example.com/", "title": "Example", "text": "hello"},
        }

    def open_session(self, *, headers, body):  # noqa: ANN001
        self.calls.append(("open", dict(headers), dict(body)))
        return 200, {"session_id": "q-1", "request_id": "ui-req-1", "status": "waiting"}

    def get_session(self, *, headers, request_id):  # noqa: ANN001
        self.calls.append(("get", dict(headers), {"request_id": request_id}))
        return 200, {"request_id": request_id, "status": "waiting"}

    def activate_session(self, *, headers, request_id):  # noqa: ANN001
        self.calls.append(("activate", dict(headers), {"request_id": request_id}))
        return 200, {"request_id": request_id, "status": "active", "slot_id": "slot-1"}

    def agent_action(self, *, headers, operation, params, request_id):  # noqa: ANN001
        self.calls.append(("agent:" + operation, dict(headers), dict(params)))
        assert operation == "page_info" or "target_tab_id" in params
        return 200, dict(self.agent_response)


def _surface(
    principal: str | None = "pmo-owner-001",
    router: _FakeRouterClient | None = None,
) -> tuple[ViewerSessionSurface, _FakeRouterClient]:
    router = router or _FakeRouterClient()
    identity = _FakeIdentityLinkClient(principal)
    return ViewerSessionSurface(identity_client=identity, router_api=router), router


def _http_server(surface: ViewerSessionSurface):
    server = create_viewer_server(
        None,
        address=("127.0.0.1", 0),
        allow_edge_identity=True,
        session_surface=surface,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


def _stop(server, thread) -> None:
    server.shutdown()
    server.server_close()


class TestSurfaceAgentRelay:
    def test_page_info_relays_to_router_with_identity_headers(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "page_info", headers=_EDGE_HEADERS, params={"target_tab_id": "tab-1"}, request_id="r1"
        )
        assert status == 200
        assert payload["status"] == "ok"
        assert payload["page"]["title"] == "Example"
        kind, headers, _params = router.calls[0]
        assert kind == "agent:page_info"
        assert headers.get("remote-sub") == "oidc-sub-1"
        assert "Cookie" not in headers and "Authorization" not in headers

    def test_forbidden_operation_is_refused_locally(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "raw_cdp", headers=_EDGE_HEADERS, params={}, request_id="r1"
        )
        assert status == 200
        assert payload["error_code"] == "capability_denied"
        assert router.calls == []

    def test_unknown_operation_is_refused_locally(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "screenshot_all", headers=_EDGE_HEADERS, params={}, request_id="r1"
        )
        assert status == 200
        assert payload["error_code"] == "operation_not_supported"
        assert router.calls == []

    def test_unresolvable_identity_fails_closed(self) -> None:
        surface, router = _surface(principal=None)
        status, payload = surface.agent(
            "page_info", headers={}, params={}, request_id="r1"
        )
        assert status == 401
        assert payload["error_code"] == "unauthorized"
        assert router.calls == []

    def test_oversized_url_is_rejected_before_relay(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "navigate",
            headers=_EDGE_HEADERS,
            params={"url": "https://example.com/" + "a" * 3000},
            request_id="r1",
        )
        assert status == 200
        assert payload["error_code"] == "invalid_request"
        assert router.calls == []

    def test_non_http_url_is_rejected(self) -> None:
        surface, router = _surface()
        for url in ("file:///etc/passwd", "javascript:alert(1)", "ftp://x"):
            status, payload = surface.agent(
                "navigate", headers=_EDGE_HEADERS, params={"url": url}, request_id="r1"
            )
            assert payload["error_code"] == "invalid_request"
        assert router.calls == []

    def test_url_with_userinfo_is_rejected(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "navigate",
            headers=_EDGE_HEADERS,
            params={"url": "https://user:pass@example.com/"},
            request_id="r1",
        )
        assert payload["error_code"] == "invalid_request"
        assert router.calls == []

    def test_oversized_selector_and_text_are_rejected(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "click", headers=_EDGE_HEADERS, params={"selector": "a" * 600}, request_id="r1"
        )
        assert payload["error_code"] == "invalid_request"
        status, payload = surface.agent(
            "type",
            headers=_EDGE_HEADERS,
            params={"selector": "#q", "text": "x" * 5000},
            request_id="r1",
        )
        assert payload["error_code"] == "invalid_request"
        assert router.calls == []

    def test_non_string_params_are_rejected(self) -> None:
        surface, router = _surface()
        status, payload = surface.agent(
            "navigate", headers=_EDGE_HEADERS, params={"url": 123}, request_id="r1"
        )
        assert payload["error_code"] == "invalid_request"
        status, payload = surface.agent(
            "click", headers=_EDGE_HEADERS, params={"selector": None}, request_id="r1"
        )
        assert payload["error_code"] == "invalid_request"
        assert router.calls == []

    def test_router_failure_is_bounded(self) -> None:
        class _Exploding(_FakeRouterClient):
            def agent_action(self, *, headers, operation, params, request_id):  # noqa: ANN001
                raise RuntimeError("boom")

        surface, _ = _surface(router=_Exploding())
        status, payload = surface.agent(
            "page_info", headers=_EDGE_HEADERS, params={"target_tab_id": "tab-1"}, request_id="r1"
        )
        assert status == 200
        assert payload["status"] == "failed"
        assert payload["error_code"] == "agent_failed"
        assert "boom" not in json.dumps(payload)


class TestAgentHttpRoutes:
    def test_post_agent_page_info_drives_the_router(self) -> None:
        surface, router = _surface()
        server, thread, base = _http_server(surface)
        try:
            request = Request(
                base + "/ui/agent/page_info",
                data=json.dumps({"params": {"target_tab_id": "tab-1"}}).encode(),
                method="POST",
                headers={**_EDGE_HEADERS, "Content-Type": "application/json"},
            )
            response = urlopen(request, timeout=5)
            assert response.status == 200
            body = json.loads(response.read().decode())
            assert body["status"] == "ok"
            assert router.calls[0][0] == "agent:page_info"
        finally:
            _stop(server, thread)

    def test_agent_route_without_identity_is_401(self) -> None:
        surface, _ = _surface(principal=None)
        server, thread, base = _http_server(surface)
        try:
            request = Request(
                base + "/ui/agent/page_info",
                data=json.dumps({"params": {"target_tab_id": "tab-1"}}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(HTTPError) as exc:
                urlopen(request, timeout=5)
            assert exc.value.code == 401
        finally:
            _stop(server, thread)

    def test_agent_route_rejects_get_and_traversal(self) -> None:
        surface, router = _surface()
        server, thread, base = _http_server(surface)
        try:
            with pytest.raises(HTTPError) as exc:
                urlopen(base + "/ui/agent/page_info", timeout=5)
            assert exc.value.code in (401, 404)
            # Traversal-looking operation tokens must fail closed with a
            # bounded envelope and never reach the router.
            for path in ("/ui/agent/..%2F..%2Fsession", "/ui/agent/../session"):
                request = Request(
                    base + path,
                    data=b"{}",
                    method="POST",
                    headers={**_EDGE_HEADERS, "Content-Type": "application/json"},
                )
                response = urlopen(request, timeout=5)
                body = json.loads(response.read().decode())
                assert response.status == 200
                assert body["status"] == "failed"
                assert body["error_code"] in (
                    "operation_not_supported",
                    "invalid_request",
                )
            assert router.calls == []
        finally:
            _stop(server, thread)

    def test_agent_route_forbidden_operation_is_bounded(self) -> None:
        surface, _ = _surface()
        server, thread, base = _http_server(surface)
        try:
            request = Request(
                base + "/ui/agent/cookies",
                data=json.dumps({"params": {"target_tab_id": "tab-1"}}).encode(),
                method="POST",
                headers={**_EDGE_HEADERS, "Content-Type": "application/json"},
            )
            response = urlopen(request, timeout=5)
            body = json.loads(response.read().decode())
            assert body["error_code"] == "capability_denied"
        finally:
            _stop(server, thread)


class TestShellUI:
    def test_shell_auto_drives_the_session(self) -> None:
        surface, _ = _surface()
        server, thread, base = _http_server(surface)
        try:
            request = Request(
                base + "/", headers={**_EDGE_HEADERS, "Accept": "text/html"}
            )
            response = urlopen(request, timeout=5)
            body = response.read().decode()
            assert response.status == 200
            # The shell bootstraps itself: joins, polls status, activates.
            assert "/ui/session/join" in body
            assert "/ui/session" in body
            assert "/ui/session/activate" in body
            # It drives allowlisted agent operations only.
            assert "/ui/agent/" in body
            for forbidden in ("raw_cdp", "evaluate", "cookies"):
                assert forbidden not in body
            # The placeholder text is gone.
            assert "No interactive browser surface" not in body
            # No external assets; everything is inline.
            assert "<script src=" not in body
            assert "<link " not in body
        finally:
            _stop(server, thread)

    def test_shell_never_contains_identity_values(self) -> None:
        surface, _ = _surface(principal="pmo-owner-001")
        server, thread, base = _http_server(surface)
        try:
            request = Request(
                base + "/",
                headers={**_EDGE_HEADERS, "Remote-Sub": "SECRET-SUB-VALUE"},
            )
            response = urlopen(request, timeout=5)
            body = response.read().decode()
            assert "SECRET-SUB-VALUE" not in body
            assert "jdoe@example.com" not in body
        finally:
            _stop(server, thread)

    def test_shell_still_fails_closed_without_identity(self) -> None:
        surface, _ = _surface()
        server, thread, base = _http_server(surface)
        try:
            with pytest.raises(HTTPError) as exc:
                urlopen(base + "/", timeout=5)
            assert exc.value.code == 401
        finally:
            _stop(server, thread)
