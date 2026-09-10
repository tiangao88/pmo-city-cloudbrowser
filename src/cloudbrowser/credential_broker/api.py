"""Capability-only, status-only transport for ``credential-broker/v1``."""

from __future__ import annotations

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping, Protocol

from cloudbrowser.credential_capability import CapabilityCodec, CapabilityError

from .contracts import BrokerResult, GrantAuthorization, LoginIntent, SiteDeclaration
from .coordinator import BrokerCoordinator
from .deadline import BrokerDeadline, BrokerDeadlineExceeded
from .idempotency import DurableIdempotencyStore, IdempotencyStoreError, OperationScope
from .nonce_store import DurableNonceStore, NonceStoreError
from .service import ResolvedBinding

_CAPABILITY_REQUEST_FIELDS = frozenset({"capability"})
_OPERATION = "credential.login"


class BindingProvider(Protocol):
    """Resolve a current broker binding from server-owned state."""

    def resolve(self, intent: LoginIntent) -> ResolvedBinding: ...


class GrantAuthorizationProvider(Protocol):
    """Resolve a grant item from server-owned principal/site/target state."""

    def resolve(
        self,
        binding: ResolvedBinding,
        site_id: str,
        target_tab_id: str,
    ) -> GrantAuthorization: ...


class TargetPreflightProvider(Protocol):
    """Probe the exact target without reading or returning credentials."""

    def preflight(
        self,
        intent: LoginIntent,
        declaration: SiteDeclaration,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Compatibility test-only identity seam; production HTTP does not use it."""

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
    """Authenticate one exact capability request and execute its claims.

    ``principal_for`` is retained only as an unreachable compatibility seam for
    old direct unit construction. ``handle`` never accepts the obsolete auth-token
    request shape and never invokes that resolver.
    """

    def __init__(
        self,
        *,
        server_identity: ServerIdentity,
        capability_codec: CapabilityCodec | None = None,
        capability_audience: str | None = None,
        deployment: str | None = None,
        nonce_store: DurableNonceStore | None = None,
        idempotency_store: DurableIdempotencyStore | None = None,
        coordinator: BrokerCoordinator | None = None,
        fetch_credentials: CredentialFetcher | None = None,
        clock: Callable[[], int | float] | None = None,
        principal_for: PrincipalResolver | None = None,
        binding_provider: BindingProvider | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        outer_timeout_s: float = 30.0,
    ) -> None:
        self._server_identity = server_identity
        self._capability_codec = capability_codec
        self._capability_audience = capability_audience
        self._deployment = deployment
        self._nonce_store = nonce_store
        self._idempotency_store = idempotency_store
        self._coordinator = coordinator
        self._fetch_credentials = fetch_credentials
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable")
        if (
            isinstance(outer_timeout_s, bool)
            or not isinstance(outer_timeout_s, (int, float))
            or outer_timeout_s <= 0
        ):
            raise ValueError("outer_timeout_s must be positive")
        self._outer_timeout_s = float(outer_timeout_s)
        self._test_only_compatibility_principal_for = principal_for
        self._test_only_compatibility_binding_provider = binding_provider

    @contextmanager
    def handle(self, path: str, payload: Mapping[str, object]) -> Iterator[BrokerResponse]:
        if path != "/v1/credential/login":
            raise LookupError("broker route not found")
        if not isinstance(payload, Mapping) or set(payload) != _CAPABILITY_REQUEST_FIELDS:
            yield _failure("missing", "invalid_request")
            return
        token = payload.get("capability")
        if not isinstance(token, str) or not token:
            yield _failure("missing", "invalid_request")
            return
        if (
            self._capability_codec is None
            or self._nonce_store is None
            or self._idempotency_store is None
            or not self._capability_audience
            or not self._deployment
            or self._clock is None
        ):
            yield _failure("missing", "broker_not_configured")
            return

        try:
            now_raw = self._clock()
            if isinstance(now_raw, bool) or not isinstance(now_raw, (int, float)):
                raise CapabilityError("capability clock is invalid")
            now = int(now_raw)
            capability = self._capability_codec.decode(
                token,
                now=now_raw,
                audience=self._capability_audience,
                deployment=self._deployment,
                operation=_OPERATION,
            )
        except CapabilityError:
            yield _failure("missing", "invalid_capability")
            return

        request_id = capability.request_id
        try:
            receipt_monotonic = float(self._monotonic_clock())
            if not math.isfinite(receipt_monotonic):
                raise ValueError("monotonic clock is invalid")
            capability_budget_s = float(capability.expires_at) - float(now_raw)
            deadline = BrokerDeadline.from_receipt(
                receipt_monotonic=receipt_monotonic,
                budget_s=min(self._outer_timeout_s, capability_budget_s),
                monotonic_clock=self._monotonic_clock,
            )
            deadline.check()
        except (ValueError, BrokerDeadlineExceeded):
            yield _failure(request_id, "deadline_exceeded")
            return
        try:
            if deadline is not None:
                deadline.check()
            consumed = self._nonce_store.consume(
                deployment=capability.deployment,
                audience=capability.audience,
                nonce=capability.nonce,
                expires_at=capability.expires_at,
                now=now,
                deadline=deadline,
            )
        except BrokerDeadlineExceeded:
            yield _failure(request_id, "deadline_exceeded")
            return
        except (NonceStoreError, OSError):
            yield _failure(request_id, "replay_protection_unavailable")
            return
        if not consumed:
            yield _failure(request_id, "capability_replayed")
            return

        if self._coordinator is None or self._fetch_credentials is None:
            yield _failure(request_id, "broker_not_configured")
            return
        coordinator = self._coordinator
        fetch_credentials = self._fetch_credentials
        assert coordinator is not None
        assert fetch_credentials is not None
        idempotency_store = self._idempotency_store
        assert idempotency_store is not None
        intent = LoginIntent(
            request_id=capability.request_id,
            profile_id=capability.profile_id,
            principal_id=capability.principal_id,
            browser_id=capability.browser_id,
            site_id=capability.site_id,
            target_tab_id=capability.target_tab_id,
            idempotency_key=capability.request_id,
            binding_generation=capability.generation,
        )
        scope = OperationScope(
            deployment=capability.deployment,
            audience=capability.audience,
            operation=capability.operation,
            profile_id=capability.profile_id,
            principal_id=capability.principal_id,
            browser_id=capability.browser_id,
            generation=capability.generation,
            site_id=capability.site_id,
            target_tab_id=capability.target_tab_id,
            request_id=capability.request_id,
        )
        try:
            if deadline is not None:
                deadline.check()
            result = idempotency_store.execute(
                scope,
                lambda: coordinator.execute(
                    intent,
                    fetch_credentials=fetch_credentials,
                    deadline=deadline,
                ),
                deadline=deadline,
            )
        except BrokerDeadlineExceeded:
            yield _failure(request_id, "deadline_exceeded")
            return
        except (IdempotencyStoreError, OSError):
            yield _failure(request_id, "idempotency_unavailable")
            return
        except Exception:
            yield _failure(request_id, "internal_error")
            return
        yield BrokerResponse(body=result.to_public_dict())


def _failure(request_id: str, error_code: str) -> BrokerResponse:
    return BrokerResponse(BrokerResult(request_id, "failed", error_code).to_public_dict())


__all__ = [
    "AuthenticatedPrincipal",
    "BindingProvider",
    "BrokerHttpServer",
    "BrokerResponse",
    "GrantAuthorizationProvider",
    "ServerIdentity",
    "TargetPreflightProvider",
]
