"""Broker idempotency store (PRD-BR-01 idempotency key field).

The store keeps a single bounded ``BrokerResult`` keyed by
(principal_id, idempotency_key). It is broker-local (in-memory here, durable
storage is a separate W4 concern) and never carries credential-shaped data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import BrokerResult


@dataclass
class IdempotencyStore:
    _records: dict[tuple[str, str], BrokerResult] = field(default_factory=dict)

    def record(self, principal_id: str, idempotency_key: str, result: BrokerResult) -> None:
        key = (principal_id, idempotency_key)
        self._records.setdefault(key, result)

    def replay(self, principal_id: str, idempotency_key: str) -> BrokerResult | None:
        return self._records.get((principal_id, idempotency_key))
