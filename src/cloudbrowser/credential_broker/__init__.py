"""Credential Broker contract and orchestration primitives."""

from ..security import BROKER_STATUS_VALUES
from .api import AuthenticatedPrincipal, BrokerHttpServer, BrokerResponse, ServerIdentity
from .audit import AuditEmitter, AuditEvent, AuditEventType, build_event
from .contracts import BrokerResult, LoginIntent, SiteDeclaration
from .coordinator import BrokerCoordinator
from .idempotency import IdempotencyStore
from .service import AdapterResult, BrokerService, LoginAdapter, ResolvedBinding

__all__ = [
    "AdapterResult",
    "AuditEmitter",
    "AuditEvent",
    "AuditEventType",
    "AuthenticatedPrincipal",
    "BROKER_STATUS_VALUES",
    "BrokerCoordinator",
    "BrokerHttpServer",
    "BrokerResponse",
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
