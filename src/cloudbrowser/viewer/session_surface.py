"""Authenticated viewer-to-router session surface.

The viewer is the component the Traefik/TinyAuth edge already
authenticates, so it is the component that drives the router control
plane on the employee's behalf: the browser UI cannot forward the
forward-auth identity headers itself, and the router must never accept
caller-supplied slot or binding fields.

The surface applies the same fail-closed rules as every other PMO
surface:

- identity is resolved through the shared identity-link client only;
  ``Remote-Email`` is never an authority and raw edge headers are never
  forwarded downstream;
- an unresolvable or failing identity lookup is 401, never a fallback;
- downstream router failures are mapped to bounded envelopes without
  leaking exception text, principal IDs, or binding tuples.
"""

from __future__ import annotations

from typing import Mapping, Protocol


class _IdentityPort(Protocol):
    def resolve(self, identity: object) -> str | None: ...


class _RouterPort(Protocol):
    def open_session(
        self, *, headers: Mapping[str, str], body: Mapping[str, object]
    ) -> tuple[int, dict[str, object]]: ...

    def get_session(
        self, *, headers: Mapping[str, str], request_id: str
    ) -> tuple[int, dict[str, object]]: ...

    def activate_session(
        self, *, headers: Mapping[str, str], request_id: str
    ) -> tuple[int, dict[str, object]]: ...

    def leave_session(
        self, *, headers: Mapping[str, str], request_id: str
    ) -> tuple[int, dict[str, object]]: ...

    def agent_action(
        self,
        *,
        headers: Mapping[str, str],
        operation: str,
        params: Mapping[str, object],
        request_id: str,
    ) -> tuple[int, dict[str, object]]: ...


_UNAUTHORIZED: tuple[int, dict[str, object]] = (401, {"ok": False, "error_code": "unauthorized"})

# Allowlisted agent operations relayed to the router; anything else is
# refused locally, before any router contact.
_AGENT_ALLOWED_OPERATIONS = frozenset({"navigate", "click", "type", "page_info", "tabs_list"})

# Param bounds enforced before relay; oversized or non-string values are
# invalid requests, never truncated.
_MAX_AGENT_URL = 2048
_MAX_AGENT_SELECTOR = 512
_MAX_AGENT_TEXT = 4096

# The only headers relayed to the router: the edge-copied identity
# attributes the router itself resolves through the identity-link service.
# Cookies, bearer tokens, and every other caller header are dropped.
_IDENTITY_HEADER_ALLOWLIST = (
    "remote-sub",
    "remote-user",
    "remote-email",
    "remote-name",
    "remote-groups",
)


def _validate_request_id(request_id: str) -> None:
    """Reject path-unsafe request ids before they reach a URL segment."""
    if (
        not isinstance(request_id, str)
        or not request_id
        or len(request_id) > 128
        or any(char in request_id for char in "/?#\r\n\x00")
        or request_id.startswith(".")
    ):
        raise RouterUnavailable("request id is not usable in a router path")


def _relay_headers(headers: Mapping[str, object]) -> dict[str, str]:
    """Return only the allowlisted identity headers, case-insensitively."""
    lowered: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).lower()
        if name in _IDENTITY_HEADER_ALLOWLIST and isinstance(value, str):
            lowered.setdefault(name, value)
    return lowered


class RouterHttpClient:
    """Bounded stdlib HTTP client for the router control plane.

    Only the three session routes are reachable; request and response
    bodies are bounded, and non-JSON or oversized responses fail closed
    instead of surfacing raw transport errors.
    """

    _MAX_BODY_BYTES = 64 * 1024

    def __init__(self, *, base_url: str, timeout_s: float = 5.0) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise ValueError("base_url must be an HTTP(S) origin without userinfo")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("base_url must not include a path or query")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_s = timeout_s

    def post_json(
        self, path: str, *, headers: Mapping[str, str], body: Mapping[str, object]
    ) -> tuple[int, dict[str, object]]:
        return self._call("POST", path, headers=headers, body=body)

    def get_json(
        self, path: str, *, headers: Mapping[str, str]
    ) -> tuple[int, dict[str, object]]:
        return self._call("GET", path, headers=headers, body=None)

    # RouterApi protocol adapters used by ViewerSessionSurface.

    def open_session(
        self, *, headers: Mapping[str, str], body: Mapping[str, object]
    ) -> tuple[int, dict[str, object]]:
        return self.post_json("/v1/session", headers=headers, body=body)

    def get_session(
        self, *, headers: Mapping[str, str], request_id: str
    ) -> tuple[int, dict[str, object]]:
        # The router derives the caller's current session from identity;
        # GET /v1/session takes no path parameter.
        return self.get_json("/v1/session", headers=headers)

    def activate_session(
        self, *, headers: Mapping[str, str], request_id: str
    ) -> tuple[int, dict[str, object]]:
        # Activation always targets the caller's own session; the router
        # resolves it from identity, never from a caller-supplied id.
        return self.post_json("/v1/session/activate", headers=headers, body={})

    def leave_session(
        self, *, headers: Mapping[str, str], request_id: str
    ) -> tuple[int, dict[str, object]]:
        # Leaving always targets the caller's own session; the router
        # resolves it from identity, never from a caller-supplied id.
        return self.post_json(
            "/v1/session/leave", headers=headers, body={"request_id": request_id}
        )

    def agent_action(
        self,
        *,
        headers: Mapping[str, str],
        operation: str,
        params: Mapping[str, object],
        request_id: str,
    ) -> tuple[int, dict[str, object]]:
        # The router validates the operation against its own allowlist and
        # derives slot/binding from the caller's active session.
        return self.post_json(
            f"/v1/agent/{operation}",
            headers=headers,
            body={"request_id": request_id, "params": dict(params)},
        )

    def _call(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, object] | None,
    ) -> tuple[int, dict[str, object]]:
        import json as _json
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        data = (
            _json.dumps(dict(body or {}), separators=(",", ":")).encode("utf-8")
            if body is not None
            else None
        )
        request = Request(self._base_url + path, data=data, method=method)
        for key, value in headers.items():
            request.add_header(key, value)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                status = int(response.status)
                raw = response.read(self._MAX_BODY_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RouterUnavailable("router control plane is unavailable") from exc
        if len(raw) > self._MAX_BODY_BYTES:
            raise RouterUnavailable("router response exceeded the size bound")
        try:
            payload = _json.loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            raise RouterUnavailable("router returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RouterUnavailable("router returned an unexpected payload")
        return status, payload


class RouterUnavailable(RuntimeError):
    """The router control plane could not be reached or answered invalidly."""


class ViewerSessionSurface:
    """Resolve the caller's principal and relay bounded session actions."""

    def __init__(self, *, identity_client: _IdentityPort, router_api: _RouterPort) -> None:
        self._identity = identity_client
        self._router = router_api

    def _principal_from_headers(self, headers: Mapping[str, object]) -> str | None:
        from cloudbrowser.edge_auth import parse_edge_identity

        identity = parse_edge_identity({key: value for key, value in headers.items()})
        if identity is None:
            return None
        try:
            principal = self._identity.resolve(identity)
        except Exception:
            return None
        if not isinstance(principal, str) or not principal or len(principal) > 256:
            return None
        return principal

    def join(
        self, *, headers: Mapping[str, object], request_id: str
    ) -> tuple[int, dict[str, object]]:
        principal = self._principal_from_headers(headers)
        if principal is None:
            return _UNAUTHORIZED
        # The router derives everything from the resolved principal; the
        # relay carries only the bounded request id. Raw edge headers are
        # deliberately not forwarded.
        try:
            status, payload = self._router.open_session(
                headers=_relay_headers(headers), body={"request_id": request_id}
            )
        except Exception:
            return (
                200,
                {"ok": False, "request_id": request_id, "status": "failed",
                "error_code": "join_failed"},
            )
        return status, dict(payload)

    def status(
        self, *, headers: Mapping[str, object], request_id: str
    ) -> tuple[int, dict[str, object]]:
        principal = self._principal_from_headers(headers)
        if principal is None:
            return _UNAUTHORIZED
        try:
            status, payload = self._router.get_session(
                headers=_relay_headers(headers), request_id=request_id
            )
        except Exception:
            return (
                200,
                {"ok": False, "request_id": request_id, "status": "failed",
                "error_code": "status_failed"},
            )
        return status, dict(payload)

    def activate(
        self, *, headers: Mapping[str, object], request_id: str
    ) -> tuple[int, dict[str, object]]:
        principal = self._principal_from_headers(headers)
        if principal is None:
            return _UNAUTHORIZED
        try:
            status, payload = self._router.activate_session(
                headers=_relay_headers(headers), request_id=request_id
            )
        except Exception:
            return (
                200,
                {"ok": False, "request_id": request_id, "status": "failed",
                "error_code": "activate_failed"},
            )
        return status, dict(payload)

    def leave(
        self, *, headers: Mapping[str, object], request_id: str
    ) -> tuple[int, dict[str, object]]:
        """Release the caller's own session (queue exit or slot release)."""
        principal = self._principal_from_headers(headers)
        if principal is None:
            return _UNAUTHORIZED
        try:
            status, payload = self._router.leave_session(
                headers=_relay_headers(headers), request_id=request_id
            )
        except Exception:
            return (
                200,
                {"ok": False, "request_id": request_id, "status": "failed",
                "error_code": "leave_failed"},
            )
        return status, dict(payload)

    def agent(
        self,
        operation: str,
        *,
        headers: Mapping[str, object],
        params: Mapping[str, object],
        request_id: str,
    ) -> tuple[int, dict[str, object]]:
        """Relay one allowlisted page action for the caller's active session.

        The operation must be in the local allowlist and every param value
        must be a bounded string; anything else is refused before the router
        is contacted. The slot, binding, and generation come exclusively
        from the caller's own router session.
        """
        principal = self._principal_from_headers(headers)
        if principal is None:
            return _UNAUTHORIZED
        if operation not in _AGENT_ALLOWED_OPERATIONS:
            error_code = (
                "capability_denied"
                if operation in ("raw_cdp", "evaluate", "cookies", "storage", "network")
                else "operation_not_supported"
            )
            return 200, {
                "ok": False, "request_id": request_id,
                "status": "failed", "error_code": error_code,
            }
        if not self._agent_params_valid(operation, params):
            return 200, {
                "ok": False, "request_id": request_id,
                "status": "failed", "error_code": "invalid_request",
            }
        try:
            status, payload = self._router.agent_action(
                headers=_relay_headers(headers),
                operation=operation,
                params=dict(params),
                request_id=request_id,
            )
        except Exception:
            return (
                200,
                {"ok": False, "request_id": request_id, "status": "failed",
                "error_code": "agent_failed"},
            )
        return status, dict(payload)

    @staticmethod
    def _agent_params_valid(
        operation: str, params: Mapping[str, object]
    ) -> bool:
        limits = {
            "navigate": {"url": _MAX_AGENT_URL},
            "click": {"selector": _MAX_AGENT_SELECTOR},
            "type": {"selector": _MAX_AGENT_SELECTOR, "text": _MAX_AGENT_TEXT},
            "page_info": {},
            "tabs_list": {},
        }
        allowed = limits[operation]
        for key, value in params.items():
            if key not in allowed or not isinstance(value, str):
                return False
            if len(value) > allowed[key]:
                return False
        if operation == "navigate":
            from urllib.parse import urlsplit

            parsed = urlsplit(str(params.get("url", "")))
            if parsed.scheme not in ("http", "https"):
                return False
            if not parsed.netloc or parsed.username or parsed.password:
                return False
        return True
