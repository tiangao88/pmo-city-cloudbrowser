"""Credential Broker contract and orchestration primitives."""

from ..security import BROKER_STATUS_VALUES
from .audit import AuditEmitter, AuditEventType, build_event
from .contracts import BrokerResult, LoginIntent, SiteDeclaration
from .coordinator import BrokerCoordinator
from .idempotency import IdempotencyStore
from .service import AdapterResult, BrokerService, LoginAdapter, ResolvedBinding
from .api import AuthenticatedPrincipal, BrokerHttpServer, ServerIdentity

__all__ = [
    "AdapterResult",
    "AuditEmitter",
    "AuditEventType",
    "AuthenticatedPrincipal",
    "BROKER_STATUS_VALUES",
    "BrokerCoordinator",
    "BrokerHttpServer",
    "BrokerResult",
    "BrokerService",
    "IdempotencyStore",
    "LoginAdapter",
    "LoginIntent",
    "ResolvedBinding",
    "ServerIdentity",
    "SiteDeclaration",
    "build_event",
]
