"""Signed capability codec and router-side login forwarding contracts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Mapping


_VERSION = "v1"
_MAX_FIELD_BYTES = 256
_MAX_REQUEST_ID_BYTES = 128
_MAX_NONCE_BYTES = 128
_MAX_TTL_S = 300
_REQUIRED_FIELDS = frozenset(
    {
        "profile_id", "principal_id", "browser_id", "generation", "site_id",
        "target_tab_id", "operation", "request_id", "audience", "deployment",
        "issued_at", "expires_at", "nonce",
    }
)


class CapabilityError(ValueError):
    """Capability failed authentication, validation, context, or time checks."""


@dataclass(frozen=True)
class CredentialCapability:
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str
    site_id: str
    target_tab_id: str
    operation: str
    request_id: str
    audience: str
    deployment: str
    issued_at: int
    expires_at: int
    nonce: str

    def __post_init__(self) -> None:
        for name in (
            "profile_id", "principal_id", "browser_id", "generation", "site_id",
            "target_tab_id", "operation", "audience", "deployment",
        ):
            _require_text(getattr(self, name), name, _MAX_FIELD_BYTES)
        _require_text(self.request_id, "request_id", _MAX_REQUEST_ID_BYTES)
        _require_text(self.nonce, "nonce", _MAX_NONCE_BYTES)
        if not _is_canonical_identifier(self.nonce):
            raise ValueError("nonce is invalid")
        if self.operation != "credential.login":
            raise ValueError("operation must be credential.login")
        for value, name in ((self.issued_at, "issued_at"), (self.expires_at, "expires_at")):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer timestamp")
        if self.expires_at <= self.issued_at or self.expires_at - self.issued_at > _MAX_TTL_S:
            raise ValueError("capability lifetime is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id, "principal_id": self.principal_id,
            "browser_id": self.browser_id, "generation": self.generation,
            "site_id": self.site_id, "target_tab_id": self.target_tab_id,
            "operation": self.operation, "request_id": self.request_id,
            "audience": self.audience, "deployment": self.deployment,
            "issued_at": self.issued_at, "expires_at": self.expires_at,
            "nonce": self.nonce,
        }


class CapabilityCodec:
    """HMAC-SHA256 codec; replay consumption belongs to the receiver."""

    def __init__(self, secret: bytes | str) -> None:
        if isinstance(secret, str):
            secret = secret.encode()
        if not isinstance(secret, bytes) or len(secret) < 16:
            raise ValueError("capability secret must be at least 16 bytes")
        self._secret = secret

    def encode(self, capability: CredentialCapability) -> str:
        if not isinstance(capability, CredentialCapability):
            raise TypeError("capability must be a CredentialCapability")
        payload = _b64(_canonical_json(capability.to_dict()))
        signed = f"{_VERSION}.{payload}".encode()
        signature = hmac.new(self._secret, signed, hashlib.sha256).digest()
        return f"{_VERSION}.{payload}.{_b64(signature)}"

    def decode(
        self, token: str, *, now: int | float, audience: str | None = None,
        deployment: str | None = None, operation: str | None = None,
    ) -> CredentialCapability:
        if not isinstance(token, str) or len(token) > 16 * 1024:
            raise CapabilityError("capability token is invalid")
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _VERSION or not parts[1] or not parts[2]:
            raise CapabilityError("capability token is invalid")
        try:
            payload = _b64decode(parts[1])
            signature = _b64decode(parts[2])
        except (ValueError, UnicodeError) as exc:
            raise CapabilityError("capability token is invalid") from exc
        signed = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(self._secret, signed, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise CapabilityError("capability signature is invalid")
        try:
            raw = json.loads(payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CapabilityError("capability payload is invalid") from exc
        if not isinstance(raw, dict) or set(raw) != _REQUIRED_FIELDS:
            raise CapabilityError("capability claims are invalid")
        try:
            capability = CredentialCapability(**raw)
        except (TypeError, ValueError) as exc:
            raise CapabilityError("capability claims are invalid") from exc
        if isinstance(now, bool) or not isinstance(now, (int, float)):
            raise CapabilityError("capability clock is invalid")
        if now < capability.issued_at or now >= capability.expires_at:
            raise CapabilityError("capability is expired or not yet valid")
        for expected_value, actual, name in (
            (audience, capability.audience, "audience"),
            (deployment, capability.deployment, "deployment"),
            (operation, capability.operation, "operation"),
        ):
            if expected_value is not None and actual != expected_value:
                raise CapabilityError(f"capability {name} mismatch")
        return capability


def _require_text(value: object, name: str, limit: int) -> None:
    if (
        not isinstance(value, str) or not value or len(value.encode()) > limit
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{name} is invalid")


def _is_canonical_identifier(value: str) -> bool:
    return all(char.isascii() and (char.isalnum() or char in "_-~") for char in value)


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    if not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise ValueError("invalid base64url")
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode())


__all__ = ["CapabilityCodec", "CapabilityError", "CredentialCapability"]
