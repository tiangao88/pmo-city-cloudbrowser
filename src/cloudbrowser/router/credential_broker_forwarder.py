"""Router-side opaque capability forwarder for the credential broker."""

from __future__ import annotations

import json
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


_MAX_BODY_BYTES = 4096
_MAX_CAPABILITY_BYTES = 16 * 1024
_MAX_RESPONSE_BYTES = 16 * 1024
_DEFAULT_REQUEST_TIMEOUT_S = 25.0
_MAX_REQUEST_TIMEOUT_S = 30.0
_DEFAULT_CAPABILITY_TTL_S = 26
_MAX_CAPABILITY_TTL_S = 300


class CredentialBrokerForwarderError(ValueError):
    """The router supplied an invalid forwarding argument."""


class CredentialBrokerUnavailable(RuntimeError):
    """The credential broker could not be reached or returned invalid data."""


class CredentialBrokerForwarder:
    """POST one opaque signed capability to the private broker endpoint.

    Authentication is carried by the capability itself. This client never
    sends the old deployment-wide broker bearer/secret and never accepts
    credential references or material.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = _DEFAULT_REQUEST_TIMEOUT_S,
        capability_ttl_s: int = _DEFAULT_CAPABILITY_TTL_S,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("credential broker base_url must be an HTTP(S) origin")
        if (
            not isinstance(timeout_s, (int, float))
            or isinstance(timeout_s, bool)
            or timeout_s <= 0
            or timeout_s > _MAX_REQUEST_TIMEOUT_S
        ):
            raise ValueError("credential broker timeout_s must be positive and <= 30s")
        if (
            not isinstance(capability_ttl_s, int)
            or isinstance(capability_ttl_s, bool)
            or capability_ttl_s <= 0
            or capability_ttl_s > _MAX_CAPABILITY_TTL_S
        ):
            raise ValueError("credential capability TTL must be an integer between 1 and 300s")
        if timeout_s >= capability_ttl_s:
            raise ValueError("credential broker timeout_s must be shorter than capability TTL")
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_s = float(timeout_s)
        self._capability_ttl_s = capability_ttl_s

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    @property
    def capability_ttl_s(self) -> int:
        return self._capability_ttl_s

    def forward(self, capability: str, *, request_id: str) -> dict[str, object]:
        """POST one capability and correlate the broker response to request_id."""
        if (
            not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in request_id)
        ):
            raise CredentialBrokerForwarderError("request_id is invalid")
        if (
            not isinstance(capability, str)
            or not capability
            or len(capability.encode("utf-8")) > _MAX_CAPABILITY_BYTES
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in capability)
        ):
            raise CredentialBrokerForwarderError("capability is invalid")
        body = json.dumps(
            {"capability": capability}, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        if len(body) > _MAX_BODY_BYTES:
            raise CredentialBrokerForwarderError("capability request is too large")
        request = Request(
            self._base_url + "/v1/credential/login",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            },
        )
        deadline = time.monotonic() + self._timeout_s
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CredentialBrokerUnavailable("credential broker deadline expired")
            with urlopen(request, timeout=remaining) as response:
                status = int(response.status)
                if time.monotonic() >= deadline:
                    raise CredentialBrokerUnavailable("credential broker deadline expired")
                remaining = deadline - time.monotonic()
                _response_timeout(response, remaining)
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
                if time.monotonic() > deadline:
                    raise CredentialBrokerUnavailable("credential broker deadline expired")
        except HTTPError as exc:
            status = int(exc.code)
            remaining = deadline - time.monotonic()
            _response_timeout(exc, remaining)
            raw = exc.read(_MAX_RESPONSE_BYTES + 1)
        except (OSError, URLError, TimeoutError) as exc:
            raise CredentialBrokerUnavailable("credential broker is unreachable") from exc
        if status < 200 or status >= 300:
            raise CredentialBrokerUnavailable("credential broker refused the request")
        if time.monotonic() > deadline:
            raise CredentialBrokerUnavailable("credential broker deadline expired")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise CredentialBrokerUnavailable("credential broker response is too large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialBrokerUnavailable("credential broker returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise CredentialBrokerUnavailable("credential broker returned an invalid response")
        return _status_only(decoded, request_id=request_id)


def _response_timeout(response: object, remaining: float) -> float:
    """Bound urllib's socket read timeout to the remaining absolute budget."""
    if remaining <= 0:
        raise CredentialBrokerUnavailable("credential broker deadline expired")
    raw = getattr(response, "fp", None)
    raw = getattr(raw, "raw", raw)
    sock = getattr(raw, "_sock", None)
    if sock is not None and callable(getattr(sock, "settimeout", None)):
        sock.settimeout(remaining)
    return remaining


def _status_only(payload: Mapping[str, object], *, request_id: str) -> dict[str, object]:
    """Keep only the public broker result after exact request correlation."""
    status = payload.get("status")
    if not isinstance(status, str) or status not in {
        "authenticated",
        "mfa_required",
        "failed",
        "not_shared",
        "unsupported",
    }:
        raise CredentialBrokerUnavailable("credential broker returned an invalid status")
    error_code = payload.get("error_code")
    if error_code is not None and (
        not isinstance(error_code, str)
        or not error_code
        or len(error_code) > 64
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in error_code)
    ):
        raise CredentialBrokerUnavailable("credential broker returned an invalid error code")
    duration_ms = payload.get("duration_ms", 0)
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or not 0 <= duration_ms <= 86_400_000:
        raise CredentialBrokerUnavailable("credential broker returned an invalid duration")
    response_request_id = payload.get("request_id")
    if not isinstance(response_request_id, str) or not response_request_id or len(response_request_id) > 128 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in response_request_id):
        raise CredentialBrokerUnavailable("credential broker returned an invalid request id")
    if response_request_id != request_id:
        raise CredentialBrokerUnavailable("credential broker returned a mismatched request id")
    return {
        "request_id": request_id,
        "status": status,
        "error_code": error_code,
        "duration_ms": duration_ms,
    }


__all__ = [
    "CredentialBrokerForwarder",
    "CredentialBrokerForwarderError",
    "CredentialBrokerUnavailable",
]
