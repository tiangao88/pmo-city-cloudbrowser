"""Credential Broker contract and orchestration primitives."""

from ..security import BROKER_STATUS_VALUES
from .api import (
    AuthenticatedPrincipal,
    BindingProvider,
    BrokerHttpServer,
    BrokerResponse,
    GrantAuthorizationProvider,
    ServerIdentity,
    TargetPreflightProvider,
)
from .audit import AuditEmitter, AuditEvent, AuditEventType, build_event
from .contracts import BrokerResult, GrantAuthorization, LoginIntent, SiteDeclaration
from .coordinator import BrokerCoordinator
from .grant_custody import (
    CustodyCredentialFetcher,
    CustodyGrantStore,
    GrantCustodyError,
    GrantLease,
    GrantMaterialError,
    GrantRevoked,
    GrantScope,
    ProvisionedGrant,
    backup_database,
    parse_kek,
    rollback_database,
)
from .idempotency import (
    DurableIdempotencyStore,
    IdempotencyStore,
    IdempotencyStoreError,
    IdempotencyStoreFull,
    OperationScope,
    Reservation,
)
from .nonce_store import DurableNonceStore, NonceStoreError, NonceStoreFull
from .service import (
    AdapterResult,
    BrokerService,
    DependencyUnavailable,
    GrantResolver,
    LoginAdapter,
    ResolvedBinding,
    TargetPreflight,
)

__all__ = [
    "AdapterResult",
    "AuditEmitter",
    "AuditEvent",
    "AuditEventType",
    "AuthenticatedPrincipal",
    "BindingProvider",
    "BROKER_STATUS_VALUES",
    "BrokerCoordinator",
    "BrokerHttpServer",
    "BrokerResponse",
    "BrokerResult",
    "BrokerService",
    "DependencyUnavailable",
    "CustodyCredentialFetcher",
    "CustodyGrantStore",
    "GrantCustodyError",
    "GrantLease",
    "GrantMaterialError",
    "GrantRevoked",
    "GrantScope",
    "DurableIdempotencyStore",
    "DurableNonceStore",
    "GrantAuthorization",
    "GrantAuthorizationProvider",
    "GrantResolver",
    "IdempotencyStoreError",
    "IdempotencyStoreFull",
    "IdempotencyStore",
    "LoginAdapter",
    "LoginIntent",
    "NonceStoreError",
    "NonceStoreFull",
    "OperationScope",
    "ProvisionedGrant",
    "Reservation",
    "ResolvedBinding",
    "ServerIdentity",
    "SiteDeclaration",
    "TargetPreflight",
    "TargetPreflightProvider",
    "backup_database",
    "build_event",
    "parse_kek",
    "rollback_database",
]
