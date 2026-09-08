"""Viewer session surface: the authenticated UI drives the router control plane.

The public viewer root must stop being a static shell. For an
edge-authenticated employee it resolves the caller's PMO principal
server-side (never trusting ``Remote-Email``), joins the router queue on
the employee's behalf, polls session state, and activates an offered
session — the same fail-closed rules as the router API itself:

- identity is resolved through the shared identity-link client only;
- unresolved or forged identity fails closed (401);
- the UI exposes only queue metadata (status/slot/position/TTLs) and
  never the raw principal ID, binding tuples, or secret material;
- activation reuses the caller's own session; no caller-supplied
  slot/binding fields are accepted.

The surface is served by the viewer because the browser UI cannot forward
the Traefik forward-auth headers itself; the viewer is the component the
edge already authenticates.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.viewer import create_viewer_server
from cloudbrowser.viewer.session_surface import ViewerSessionSurface

_SECRET = "identity-link-test-secret-012345"
_ISSUER = "https://auth.example.test"
_REALM = "tinyauth.example.test"

_EDGE_HEADERS = {
    "Remote-Sub": "oidc-sub-1",
    "Remote-Email": "owner@example.com",
    "Remote-Groups": "PMOC_Users",
}


class _FakeIdentityLinkClient:
    """IdentityLinkClient stand-in with a fixed principal mapping."""

    def __init__(self, principal: str | None = "pmo-owner-001") -> None:
        self.principal = principal
        self.resolve_calls: list[object] = []

    def resolve(self, identity: object) -> str | None:
        self.resolve_calls.append(identity)
        return self.principal


class _FakeRouterClient:
    """RouterApi-protocol stand-in recording surface calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []
        self.open_response: dict[str, object] = {
            "session_id": "q-1",
            "request_id": "ui-req-1",
            "status": "waiting",
        }

    def open_session(self, *, headers, body):  # noqa: ANN001
        self.calls.append(("open", dict(headers), dict(body)))
        return 200, dict(self.open_response)

    def get_session(self, *, headers, request_id):  # noqa: ANN001
        self.calls.append(("get", dict(headers), {"request_id": request_id}))
        return 200, {"request_id": request_id, "status": "offered", "slot_id": "slot-1", "offer_ttl_s": 42.0}  # noqa: E501

    def activate_session(self, *, headers, request_id):  # noqa: ANN001
        self.calls.append(("activate", dict(headers), {"request_id": request_id}))
        return 200, {"request_id": request_id, "status": "active", "slot_id": "slot-1", "session_ttl_s": 3600.0}  # noqa: E501

    def leave_session(self, *, headers, request_id):  # noqa: ANN001
        self.calls.append(("leave", dict(headers), {"request_id": request_id}))
        return 200, {"request_id": request_id, "session_id": "q-1", "status": "left"}


def _surface(
    principal: str | None = "pmo-owner-001",
    router: _FakeRouterClient | None = None,
) -> tuple[ViewerSessionSurface, _FakeRouterClient]:
    identity = _FakeIdentityLinkClient(principal)
    router = router or _FakeRouterClient()
    return ViewerSessionSurface(identity_client=identity, router_api=router), router


def _http_server(surface: ViewerSessionSurface, tmp_path: Path):
    server = create_viewer_server(
        None,  # viewer not needed for the surface routes; API accepts None when surface present
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
    thread.join(timeout=3)
    server.server_close()


class TestSurfaceUnit:
    def test_join_resolves_identity_and_opens_session(self) -> None:
        surface, router = _surface()
        status, payload = surface.join(headers={"Remote-Sub": "oidc-sub-1"}, request_id="ui-req-1")
        assert status == 200
        assert payload["status"] == "waiting"
        assert router.calls[0][0] == "open"

    def test_join_does_not_forward_credentials(self) -> None:
        """The relay carries identity attributes only — never bearer/cookie material."""
        surface, router = _surface()
        surface.join(
            headers={"Remote-Sub": "oidc-sub-1", "Authorization": "Bearer x", "Cookie": "sid=y"},
            request_id="r",
        )
        forwarded = str(router.calls[0][1])
        assert "Bearer" not in forwarded and "sid=" not in forwarded

    def test_relay_forwards_only_allowlisted_identity_headers(self) -> None:
        surface, router = _surface()
        surface.join(
            headers={
                "Remote-Sub": "oidc-sub-1",
                "Remote-Groups": "PMOC_Users",
                "Cookie": "session=secret-cookie",
                "Authorization": "Bearer leaked-token",
                "X-CB-Principal": "pmo-forged",
            },
            request_id="r",
        )
        forwarded = router.calls[0][1]
        assert forwarded.get("remote-sub") == "oidc-sub-1"
        assert forwarded.get("remote-groups") == "PMOC_Users"
        assert "Cookie" not in forwarded and "cookie" not in forwarded
        assert "Authorization" not in forwarded and "authorization" not in forwarded
        assert "X-CB-Principal" not in forwarded and "x-cb-principal" not in forwarded

    def test_join_without_resolvable_principal_fails_closed(self) -> None:
        surface, router = _surface(principal=None)
        status, payload = surface.join(headers={}, request_id="r")
        assert status == 401
        assert payload["error_code"] == "unauthorized"
        assert router.calls == []

    def test_join_identity_error_fails_closed(self) -> None:
        class _Raising:
            def resolve(self, identity: object) -> str | None:
                raise RuntimeError("identity-link unavailable")

        surface = ViewerSessionSurface(identity_client=_Raising(), router_api=_FakeRouterClient())
        status, payload = surface.join(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 401
        assert payload["error_code"] == "unauthorized"

    def test_join_router_failure_is_bounded_and_fails_closed(self) -> None:
        class _Exploding:
            def open_session(self, *, headers, body):  # noqa: ANN001
                raise RuntimeError("boom")

        surface = ViewerSessionSurface(
            identity_client=_FakeIdentityLinkClient(), router_api=_Exploding()
        )
        status, payload = surface.join(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 200
        assert payload["status"] == "failed"

    def test_status_returns_queue_metadata(self) -> None:
        surface, router = _surface()
        status, payload = surface.status(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 200
        assert payload["status"] == "offered"
        assert payload["slot_id"] == "slot-1"

    def test_activate_uses_the_callers_own_session(self) -> None:
        surface, router = _surface()
        status, payload = surface.activate(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 200
        assert payload["status"] == "active"
        assert router.calls[0][0] == "activate"

    def test_leave_releases_the_callers_own_session(self) -> None:
        surface, router = _surface()
        status, payload = surface.leave(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 200
        assert payload["status"] == "left"
        assert router.calls[0][0] == "leave"
        # Same identity-header allowlist rule as every other surface relay.
        forwarded = router.calls[0][1]
        assert "authorization" not in {k.lower() for k in forwarded}

    def test_leave_without_resolvable_principal_fails_closed(self) -> None:
        surface, _router = _surface(principal=None)
        status, payload = surface.leave(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 401
        assert payload["error_code"] == "unauthorized"

    def test_leave_router_failure_is_bounded(self) -> None:
        class _Exploding:
            def leave_session(self, *, headers, request_id):  # noqa: ANN001
                raise RuntimeError("router down")

        surface = ViewerSessionSurface(identity_client=_FakeIdentityLinkClient(), router_api=_Exploding())  # noqa: E501
        status, payload = surface.leave(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 200
        assert payload["status"] == "failed"
        assert payload["error_code"] == "leave_failed"
        assert "router down" not in str(payload)

    def test_activate_on_wrong_state_fails_bounded(self) -> None:
        class _NotFound:
            def activate_session(self, *, headers, request_id):  # noqa: ANN001
                return 200, {"request_id": request_id, "status": "failed", "error_code": "session_not_found"}  # noqa: E501

            def get_session(self, *, headers, request_id):  # noqa: ANN001
                raise AssertionError("not used")

        surface = ViewerSessionSurface(identity_client=_FakeIdentityLinkClient(), router_api=_NotFound())  # noqa: E501
        status, payload = surface.activate(headers={"Remote-Sub": "oidc-sub-1"}, request_id="r")
        assert status == 200
        assert payload["error_code"] == "session_not_found"


class TestSurfaceHttp:
    def test_join_endpoint_drives_the_router(self, tmp_path: Path) -> None:
        surface, router = _surface()
        server, thread, base = _http_server(surface, tmp_path)
        try:
            request = Request(
                base + "/ui/session/join",
                data=json.dumps({"request_id": "ui-req-1"}).encode(),
                method="POST",
                headers={**_EDGE_HEADERS, "Content-Type": "application/json"},
            )
            response = urlopen(request, timeout=5)
            assert response.status == 200
            body = json.loads(response.read().decode())
            assert body["status"] == "waiting"
            assert router.calls[0][0] == "open"
        finally:
            _stop(server, thread)

    def test_join_without_identity_is_401(self, tmp_path: Path) -> None:
        surface, _router = _surface(principal=None)
        server, thread, base = _http_server(surface, tmp_path)
        try:
            request = Request(
                base + "/ui/session/join",
                data=json.dumps({"request_id": "ui-req-1"}).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(HTTPError) as exc:
                urlopen(request, timeout=5)
            assert exc.value.code == 401
        finally:
            _stop(server, thread)

    def test_status_and_activate_endpoints_exist(self, tmp_path: Path) -> None:
        surface, _router = _surface()
        server, thread, base = _http_server(surface, tmp_path)
        try:
            status_response = urlopen(
                Request(base + "/ui/session", headers=_EDGE_HEADERS), timeout=5
            )
            assert status_response.status == 200
            assert json.loads(status_response.read().decode())["status"] == "offered"
            activate_response = urlopen(
                Request(
                    base + "/ui/session/activate",
                    data=b"{}",
                    method="POST",
                    headers={**_EDGE_HEADERS, "Content-Type": "application/json"},
                ),
                timeout=5,
            )
            assert activate_response.status == 200
            assert json.loads(activate_response.read().decode())["status"] == "active"
        finally:
            _stop(server, thread)

    def test_surface_never_leaks_principal_or_edge_headers(self, tmp_path: Path) -> None:
        surface, _router = _surface()
        server, thread, base = _http_server(surface, tmp_path)
        try:
            response = urlopen(
                Request(base + "/ui/session", headers=_EDGE_HEADERS), timeout=5
            )
            body = response.read().decode()
            assert "pmo-owner-001" not in body
            assert "owner@example.com" not in body
            assert "oidc-sub-1" not in body
        finally:
            _stop(server, thread)

    def test_leave_endpoint_drives_the_router(self, tmp_path: Path) -> None:
        surface, router = _surface()
        server, thread, base = _http_server(surface, tmp_path)
        try:
            response = urlopen(
                Request(
                    base + "/ui/session/leave",
                    data=b"{}",
                    headers={**_EDGE_HEADERS, "Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=5,
            )
            assert response.status == 200
            body = json.loads(response.read().decode())
            assert body["status"] == "left"
            assert router.calls[-1][0] == "leave"
        finally:
            _stop(server, thread)

    def test_status_surfaces_edge_display_name_only(self, tmp_path: Path) -> None:
        """Remote-Name flows through as display_name; principal never leaks."""
        surface, _router = _surface()
        server, thread, base = _http_server(surface, tmp_path)
        try:
            headers = {**_EDGE_HEADERS, "Remote-Name": "Thibault Montigaud"}
            response = urlopen(
                Request(base + "/ui/session", headers=headers), timeout=5
            )
            body = json.loads(response.read().decode())
            assert body["display_name"] == "Thibault Montigaud"
            assert "pmo-owner-001" not in json.dumps(body)
            # Without the header the field is absent, not an empty fallback.
            plain = urlopen(
                Request(base + "/ui/session", headers=_EDGE_HEADERS), timeout=5
            )
            assert "display_name" not in json.loads(plain.read().decode())
        finally:
            _stop(server, thread)

    def test_health_stays_public(self, tmp_path: Path) -> None:
        surface, _router = _surface()
        server, thread, base = _http_server(surface, tmp_path)
        try:
            response = urlopen(base + "/health", timeout=5)
            assert response.status == 200
        finally:
            _stop(server, thread)
