"""Router-side HTTP/JSON client for one private slot supervisor.

Each slot supervisor owns its own ``POST /control`` endpoint (created by
``cloudbrowser.router.control_api.create_control_server``). This client is
the only place that decides which base URL backs a given ``slot_id``; the
mapping is server-supplied at construction time and never read from
network input. The client speaks the bounded JSON protocol using only
stdlib HTTP/JSON, and surfaces failure as typed exceptions so the router
control plane never echoes raw stack traces, secrets, principal IDs,
emails, or page values.
"""

from __future__ import annotations

import hmac
import json
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_ALLOWED_OPERATIONS = frozenset({"wake", "suspend", "recreate"})
_MAX_REQUEST_ID = 128
_MAX_SLOT_ID = 64
_MAX_RESPONSE_BYTES = 16 * 1024
_MIN_TRUSTED_SECRET_LENGTH = 16


class SupervisorClientError(ValueError):
    """Caller supplied an argument this client refuses locally."""


class SupervisorUnavailable(RuntimeError):
    """The supervisor could not be reached or returned an unusable response."""


class _HttpJsonRequester:
    """Minimal stdlib HTTP POST helper with bounded URL/path validation."""

    def __init__(self, base_url: str, *, timeout_s: float, trusted_secret: str) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            raise ValueError("supervisor base_url must be an HTTP(S) origin without userinfo")
        if parsed.query or parsed.fragment:
            raise ValueError("supervisor base_url must not include query or fragment")
        path = parsed.path
        if path and (not path.startswith("/") or path.startswith("//") or ".." in path.split("/")):
            raise ValueError("supervisor base_url path must be a simple absolute prefix")
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0 or timeout_s > 30:
            raise ValueError("supervisor timeout_s must be positive and <= 30s")
        _validate_trusted_secret(trusted_secret)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._base_path = path.rstrip("/")
        self._timeout_s = float(timeout_s)
        self._trusted_secret = trusted_secret

    def post(self, body: Mapping[str, object]) -> tuple[int, bytes]:
        payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request = Request(
            self._origin + self._base_path + "/control",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
                "X-CB-Trusted-Secret": self._trusted_secret,
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            return exc.code, exc.read(_MAX_RESPONSE_BYTES + 1)
        except (OSError, URLError) as exc:
            raise SupervisorUnavailable("slot supervisor is unreachable") from exc


def _validate_slot_id(slot_id: str) -> None:
    if (
        not isinstance(slot_id, str)
        or not slot_id
        or len(slot_id) > _MAX_SLOT_ID
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in slot_id)
    ):
        raise SupervisorClientError("slot_id is invalid")


def _validate_request_id(request_id: str) -> None:
    if (
        not isinstance(request_id, str)
        or not request_id
        or len(request_id) > _MAX_REQUEST_ID
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in request_id)
    ):
        raise SupervisorClientError("request_id is invalid")


def _validate_operation(operation: str) -> None:
    if not isinstance(operation, str) or operation not in _ALLOWED_OPERATIONS:
        raise SupervisorClientError("operation is not supported")


def _validate_trusted_secret(trusted_secret: str) -> None:
    if (
        not isinstance(trusted_secret, str)
        or len(trusted_secret) < _MIN_TRUSTED_SECRET_LENGTH
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in trusted_secret)
    ):
        raise ValueError("trusted_secret must be at least 16 printable characters")


class SupervisorClient:
    """Resolve ``slot_id`` to a base URL and dispatch ``POST /control``."""

    def __init__(
        self,
        slot_url_map: Mapping[str, str],
        *,
        trusted_secret: str,
        timeout_s: float = 3.0,
        requester_factory: Callable[[str, float], _HttpJsonRequester] | None = None,
    ) -> None:
        if not slot_url_map:
            raise ValueError("slot_url_map must contain at least one entry")
        _validate_trusted_secret(trusted_secret)
        requesters: dict[str, _HttpJsonRequester] = {}
        factory = requester_factory or (
            lambda origin, timeout: _HttpJsonRequester(
                origin, timeout_s=timeout, trusted_secret=trusted_secret
            )
        )
        for slot_id, base_url in slot_url_map.items():
            _validate_slot_id(slot_id)
            requesters[slot_id] = factory(base_url, timeout_s)
        self._requesters = requesters
        self._known_slots = frozenset(requesters)

    @property
    def known_slots(self) -> frozenset[str]:
        return self._known_slots

    def post_control(self, slot_id: str, *, operation: str, request_id: str) -> dict[str, object]:
        """POST ``/control`` on the supervisor backing ``slot_id``."""
        _validate_slot_id(slot_id)
        _validate_operation(operation)
        _validate_request_id(request_id)
        requester = self._requesters.get(slot_id)
        if requester is None:
            raise SupervisorClientError("slot is not configured")
        status, raw = requester.post({"operation": operation, "request_id": request_id})
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise SupervisorUnavailable("supervisor response is too large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupervisorUnavailable("supervisor returned invalid JSON") from exc
        if status >= 500:
            raise SupervisorUnavailable("supervisor request failed")
        if not isinstance(decoded, dict):
            raise SupervisorUnavailable("supervisor returned a non-object response")
        return decoded


__all__ = ["SupervisorClient", "SupervisorClientError", "SupervisorUnavailable"]
