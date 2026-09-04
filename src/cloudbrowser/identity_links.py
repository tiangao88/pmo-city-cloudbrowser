"""Client contract for the internal PMO identity-link service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cloudbrowser.edge_auth import EdgeIdentity


_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_ID_BYTES = 256


class IdentityLinkClientError(RuntimeError):
    """The internal identity-link dependency could not answer safely."""


@dataclass(frozen=True)
class IdentityLinkKey:
    """Namespaced external identity key; email is intentionally absent."""

    namespace: str
    issuer_or_realm: str
    external_id: str

    def __post_init__(self) -> None:
        if self.namespace not in {"oidc", "tinyauth-local"}:
            raise ValueError("identity namespace is invalid")
        for value in (self.issuer_or_realm, self.external_id):
            if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_ID_BYTES:
                raise ValueError("identity key value is invalid")
            if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
                raise ValueError("identity key value is invalid")


@dataclass(frozen=True)
class IdentityLinkClient:
    """Fail-closed HTTP client shared by CloudFiles and Viewer."""

    base_url: str
    shared_secret: str
    oidc_issuer: str
    tinyauth_realm: str
    timeout_s: float = 3.0
    max_response_bytes: int = _MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        if not self.shared_secret or len(self.shared_secret) < 16:
            raise ValueError("shared_secret must be at least 16 characters")
        if not isinstance(self.timeout_s, (int, float)) or self.timeout_s <= 0 or self.timeout_s > 30:
            raise ValueError("timeout_s is invalid")
        if not isinstance(self.max_response_bytes, int) or self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes is invalid")
        IdentityLinkKey("oidc", self.oidc_issuer, "probe")
        IdentityLinkKey("tinyauth-local", self.tinyauth_realm, "probe")

    @property
    def ready(self) -> bool:
        """Return true only when the internal service has a bounded health reply."""
        try:
            request = Request(self.base_url.rstrip("/") + "/health", method="GET")
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                return False
            payload = json.loads(body)
            return isinstance(payload, dict) and payload.get("status") == "ok"
        except (OSError, URLError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def resolve(self, identity: EdgeIdentity) -> str | None:
        """Resolve a parsed edge identity without ever transmitting its email."""
        groups = tuple(identity.groups)
        if "PMOC_Users" not in groups:
            return None
        if identity.sub is not None:
            key = IdentityLinkKey("oidc", self.oidc_issuer, identity.sub)
        elif identity.user is not None:
            key = IdentityLinkKey("tinyauth-local", self.tinyauth_realm, identity.user)
        else:
            return None
        return self.resolve_key(key, groups=groups)

    def resolve_key(self, key: IdentityLinkKey, *, groups: tuple[str, ...]) -> str | None:
        """Resolve one explicit key; the request contains no email field."""
        if key.namespace == "oidc" and key.issuer_or_realm != self.oidc_issuer:
            return None
        if key.namespace == "tinyauth-local" and key.issuer_or_realm != self.tinyauth_realm:
            return None
        if "PMOC_Users" not in groups:
            return None
        payload = json.dumps(
            {
                "namespace": key.namespace,
                "issuer_or_realm": key.issuer_or_realm,
                "external_id": key.external_id,
                "groups": list(groups),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            self.base_url.rstrip("/") + "/v1/resolve",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
                "X-CB-Identity-Link-Secret": self.shared_secret,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read(self.max_response_bytes + 1)
                status = response.status
        except HTTPError as exc:
            body = exc.read(self.max_response_bytes + 1)
            status = exc.code
        except (OSError, URLError) as exc:
            raise IdentityLinkClientError("identity-link service unavailable") from exc
        if len(body) > self.max_response_bytes:
            raise IdentityLinkClientError("identity-link response is too large")
        if status == 403:
            return None
        if status != 200:
            raise IdentityLinkClientError("identity-link service rejected the request")
        try:
            document = json.loads(body)
            principal = document["principal_id"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            raise IdentityLinkClientError("identity-link response is invalid") from exc
        if not isinstance(principal, str) or not principal or len(principal) > _MAX_ID_BYTES:
            raise IdentityLinkClientError("identity-link principal is invalid")
        return principal


def build_identity_link_client() -> IdentityLinkClient:
    """Build the shared resolver from explicit service configuration."""
    values = {}
    for name in (
        "CB_IDENTITY_LINK_BASE_URL",
        "CB_IDENTITY_LINK_SHARED_SECRET",
        "CB_OIDC_ISSUER",
        "CB_TINYAUTH_REALM",
    ):
        value = os.environ.get(name)
        if not value:
            raise SystemExit(f"{name} is required")
        values[name] = value
    return IdentityLinkClient(
        base_url=values["CB_IDENTITY_LINK_BASE_URL"],
        shared_secret=values["CB_IDENTITY_LINK_SHARED_SECRET"],
        oidc_issuer=values["CB_OIDC_ISSUER"],
        tinyauth_realm=values["CB_TINYAUTH_REALM"],
    )


__all__ = [
    "IdentityLinkClient",
    "IdentityLinkClientError",
    "IdentityLinkKey",
    "build_identity_link_client",
]
