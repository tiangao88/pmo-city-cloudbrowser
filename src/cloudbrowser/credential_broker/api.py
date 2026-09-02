"""Dependency-injected status-only transport for ``credential-broker/v1``."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping

from .contracts import BrokerResult, LoginIntent
from .coordinator import BrokerCoordinator


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Server-derived identity attached to one broker request."""

    profile_id: str
    principal_id: str
    browser_id: str
    site_id: str
    generation: str


@dataclass(frozen=True)
class ServerIdentity:
    component: str
    instance_id: str


@dataclass(frozen=True)
class BrokerResponse:
    body: Mapping[str, object]


PrincipalResolver = Callable[[str], AuthenticatedPrincipal]
CredentialFetcher = Callable[[str], object]


class BrokerHttpServer:
    """Small transport core; HTTP serving and authentication are injected."""

    def __init__(
        self,
        *,
        server_identity: ServerIdentity,
        principal_for: PrincipalResolver,
        coordinator: BrokerCoordinator | None = None,
        fetch_credentials: CredentialFetcher | None = None,
    ) -> None:
        self._server_identity = server_identity
        self._principal_for = principal_for
        self._coordinator = coordinator
        self._fetch_credentials = fetch_credentials

    @contextmanager
    def handle(self, path: str, payload: Mapping[str, object]) -> Iterator[BrokerResponse]:
        if path != "/v1/credential/login":
            raise LookupError("broker route not found")
        request_id = _request_id(payload)
        try:
            principal = self._principal_for(str(payload.get("auth_token", "")))
        except Exception:
            yield BrokerResponse(body=BrokerResult(request_id, "failed", "invalid_auth").to_public_dict())
            return

        mismatch = _caller_binding_mismatch(payload, principal)
        if mismatch:
            yield BrokerResponse(body=BrokerResult(request_id, "failed", "binding_mismatch").to_public_dict())
            return
        if not request_id or request_id == "missing":
            yield BrokerResponse(body=BrokerResult("missing", "failed", "invalid_request").to_public_dict())
            return
        username_ref = payload.get("username_ref")
        site_id = payload.get("site_id")
        current_url = payload.get("current_url")
        if not isinstance(username_ref, str) or not username_ref or not isinstance(site_id, str) or not site_id:
            yield BrokerResponse(body=BrokerResult(request_id, "failed", "invalid_request").to_public_dict())
            return
        if not isinstance(current_url, str) or not current_url:
            yield BrokerResponse(body=BrokerResult(request_id, "failed", "invalid_request").to_public_dict())
            return

        if self._coordinator is None or self._fetch_credentials is None:
            result = BrokerResult(request_id, "failed", "broker_not_configured")
        else:
            intent = LoginIntent(
                request_id=request_id,
                profile_id=principal.profile_id,
                principal_id=principal.principal_id,
                browser_id=principal.browser_id,
                site_id=principal.site_id,
                username_ref=username_ref,
                target_tab_id=_optional_text(payload.get("target_tab_id")),
                idempotency_key=_optional_text(payload.get("idempotency_key")),
                binding_generation=principal.generation,
            )
            result = self._coordinator.execute(intent, fetch_credentials=self._fetch_credentials)
        # Only BrokerResult.to_public_dict() is allowed across this boundary.
        yield BrokerResponse(body=result.to_public_dict())


def _request_id(payload: Mapping[str, object]) -> str:
    value = payload.get("request_id")
    return value.strip() if isinstance(value, str) and value.strip() and len(value.strip()) <= 128 else "missing"


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        return None
    return value


def _caller_binding_mismatch(payload: Mapping[str, object], principal: AuthenticatedPrincipal) -> bool:
    expected = {
        "profile_id": principal.profile_id,
        "principal_id": principal.principal_id,
        "browser_id": principal.browser_id,
        "site_id": principal.site_id,
        "binding_generation": principal.generation,
    }
    return any(key in payload and payload[key] != value for key, value in expected.items())


__all__ = ["AuthenticatedPrincipal", "BrokerHttpServer", "BrokerResponse", "ServerIdentity"]
