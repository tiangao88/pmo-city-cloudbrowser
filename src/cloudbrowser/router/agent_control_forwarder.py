"""Router-side trusted forwarder for one slot's agent-control service.

Mirrors ``router/supervisor_client.py``: the slot→base-URL mapping is
server-supplied at construction time and never read from network input, and
failures surface as typed exceptions so the router control plane never echoes
raw stack traces, secrets, principal IDs, emails, or page values.

Every forwarded request carries the trusted shared secret and the
server-derived binding (``X-CB-Principal``/``X-CB-Browser``/``X-CB-Generation``)
taken from the session record — never from caller input. Caller ``Remote-*``
edge headers are never forwarded.
"""

from __future__ import annotations

import hmac
import json
import re
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_MAX_SLOT_ID = 64
_MAX_REQUEST_ID = 128
_MAX_OPERATION = 64
_MAX_RESPONSE_BYTES = 64 * 1024
_MIN_TRUSTED_SECRET_LENGTH = 16
_MAX_PARAMS_BYTES = 8 * 1024

# Same shape the router accepts for /v1/slot/<slot_id> paths.
_SLOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Same allowlist as agent_control.ALLOWED_AGENT_OPERATIONS; duplicated here so
# forbidden operations are refused locally before any network egress.
_ALLOWED_OPERATIONS = frozenset({"navigate", "click", "type", "page_info", "tabs_list"})


def _serialize_binding(binding: object) -> dict[str, str]:
    """Bind the relay to the allowlisted BrowserBinding shape."""

    from cloudbrowser.browser_slots import BrowserBinding

    if not isinstance(binding, BrowserBinding):
        raise AgentControlForwarderError("binding must be a BrowserBinding")
    return {
        "principal_id": binding.principal_id,
        "profile_id": binding.profile_id,
        "browser_id": binding.browser_id,
        "generation": binding.generation,
    }


class AgentControlForwarderError(ValueError):
    """Caller supplied an argument this forwarder refuses locally."""


class AgentControlUnavailable(RuntimeError):
    """The agent-control endpoint could not be reached or returned an
    unusable response."""


def _validate_trusted_secret(trusted_secret: str) -> None:
    if (
        not isinstance(trusted_secret, str)
        or len(trusted_secret) < _MIN_TRUSTED_SECRET_LENGTH
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in trusted_secret)
    ):
        raise ValueError("trusted_secret must be at least 16 printable characters")


def _validate_slot_id(slot_id: str) -> None:
    if not isinstance(slot_id, str) or not _SLOT_ID_RE.fullmatch(slot_id):
        raise AgentControlForwarderError("slot_id is invalid")


def _validate_request_id(request_id: str) -> None:
    if (
        not isinstance(request_id, str)
        or not request_id
        or len(request_id) > _MAX_REQUEST_ID
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in request_id)
    ):
        raise AgentControlForwarderError("request_id is invalid")


def _validate_operation(operation: str) -> None:
    if not isinstance(operation, str) or operation not in _ALLOWED_OPERATIONS:
        raise AgentControlForwarderError("operation is not supported")


class _HttpJsonRequester:
    """Minimal stdlib HTTP POST helper with bounded URL/path validation."""

    def __init__(self, base_url: str, *, timeout_s: float, trusted_secret: str) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
            raise ValueError("agent-control base_url must be an HTTP(S) origin without userinfo")
        if parsed.query or parsed.fragment:
            raise ValueError("agent-control base_url must not include query or fragment")
        path = parsed.path
        if path and (not path.startswith("/") or path.startswith("//") or ".." in path.split("/")):
            raise ValueError("agent-control base_url path must be a simple absolute prefix")
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0 or timeout_s > 30:
            raise ValueError("agent-control timeout_s must be positive and <= 30s")
        _validate_trusted_secret(trusted_secret)
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._base_path = path.rstrip("/")
        self._timeout_s = float(timeout_s)
        self._trusted_secret = trusted_secret

    def post_lease(self, body: Mapping[str, object]) -> tuple[int, bytes]:
        """POST the trusted lease rotation to ``/agent-control/lease``."""

        payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request = Request(
            self._origin + self._base_path + "/agent-control/lease",
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
            raise AgentControlUnavailable("agent control is unreachable") from exc

    def post(
        self,
        body: Mapping[str, object],
        *,
        principal_id: str,
        browser_id: str,
        generation: str,
    ) -> tuple[int, bytes]:
        payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        request = Request(
            self._origin + self._base_path + "/agent-control/v1",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
                "X-CB-Trusted-Secret": self._trusted_secret,
                "X-CB-Principal": principal_id,
                "X-CB-Browser": browser_id,
                "X-CB-Generation": generation,
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            return exc.code, exc.read(_MAX_RESPONSE_BYTES + 1)
        except (OSError, URLError) as exc:
            raise AgentControlUnavailable("agent control is unreachable") from exc


class AgentControlForwarder:
    """Resolve ``slot_id`` to a base URL and dispatch ``POST /agent-control/v1``."""

    def __init__(
        self,
        slot_urls: Mapping[str, str],
        *,
        trusted_secret: str,
        timeout_s: float = 3.0,
        requester_factory=None,
    ) -> None:
        if not slot_urls:
            raise ValueError("slot_urls must contain at least one entry")
        _validate_trusted_secret(trusted_secret)
        requesters: dict[str, _HttpJsonRequester] = {}
        factory = requester_factory or (
            lambda origin, timeout: _HttpJsonRequester(
                origin, timeout_s=timeout, trusted_secret=trusted_secret
            )
        )
        for slot_id, base_url in slot_urls.items():
            _validate_slot_id(slot_id)
            requesters[slot_id] = factory(base_url, timeout_s)
        self._requesters = requesters
        self._known_slots = frozenset(requesters)

    @property
    def known_slots(self) -> frozenset[str]:
        return self._known_slots

    def forward(
        self,
        slot_id: str,
        *,
        binding: object,
        operation: str,
        params: Mapping[str, object],
        request_id: str,
    ) -> dict[str, object]:
        """Relay one page action to the agent-control service backing ``slot_id``.

        The binding is always the server-derived session binding; caller input
        supplies only ``operation``/``params``/``request_id``.
        """
        _validate_slot_id(slot_id)
        _validate_operation(operation)
        _validate_request_id(request_id)
        serialized = _serialize_binding(binding)
        if not isinstance(params, Mapping):
            raise AgentControlForwarderError("params must be an object")
        if len(json.dumps(dict(params), separators=(",", ":"))) > _MAX_PARAMS_BYTES:
            raise AgentControlForwarderError("params are too large")
        requester = self._requesters.get(slot_id)
        if requester is None:
            raise AgentControlForwarderError("slot is not configured")
        body: dict[str, object] = {
            "request_id": request_id,
            "operation": operation,
            "params": dict(params),
        }
        headers_binding = {
            "principal_id": serialized["principal_id"],
            "browser_id": serialized["browser_id"],
            "generation": serialized["generation"],
        }
        status, raw = requester.post(
            body,
            principal_id=headers_binding["principal_id"],
            browser_id=headers_binding["browser_id"],
            generation=headers_binding["generation"],
        )
        if status == 401:
            # Statically pinned lease: rotate it to the server-derived
            # session binding (trusted-secret gated) and retry once. The
            # binding never comes from caller input.
            lease_status, _lease_raw = requester.post_lease(
                {"binding": serialized}
            )
            if lease_status != 200:
                raise AgentControlUnavailable("agent-control refused the lease rotation")
            status, raw = requester.post(
                body,
                principal_id=headers_binding["principal_id"],
                browser_id=headers_binding["browser_id"],
                generation=headers_binding["generation"],
            )
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise AgentControlUnavailable("agent-control response is too large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentControlUnavailable("agent-control returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise AgentControlUnavailable("agent-control returned a non-object response")
        if status >= 500:
            raise AgentControlUnavailable("agent-control request failed")
        if status in (400, 401, 404):
            raise AgentControlUnavailable("agent-control refused the forwarded request")
        return decoded


__all__ = [
    "AgentControlForwarder",
    "AgentControlForwarderError",
    "AgentControlUnavailable",
]
