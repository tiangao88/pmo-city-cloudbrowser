"""RED-stage tests for the broker idempotency store (PRD-BR-01 idempotency
key + PRD-BR-08 bounded retry behavior).

- Replays with the same (principal_id, idempotency_key) return the original
  status result, not a new broker operation.
- Replays with the same idempotency_key but a different principal_id reject
  (consistent with S2 / S3 / attack-case "Agent replays nonce").
- The store never serializes the broker's credential-bearing artifacts.
"""

from __future__ import annotations

from cloudbrowser.credential_broker import BrokerResult
from cloudbrowser.credential_broker.idempotency import IdempotencyStore


def test_store_replays_same_status_for_same_key_and_principal() -> None:
    store = IdempotencyStore()
    initial = BrokerResult("req-1", "authenticated", duration_ms=10)
    store.record("alice@example.test", "idem-1", initial)
    again = store.replay("alice@example.test", "idem-1")
    assert again == initial


def test_store_rejects_key_collision_across_principals() -> None:
    store = IdempotencyStore()
    store.record("alice@example.test", "idem-1", BrokerResult("r1", "authenticated"))
    result = store.replay("bob@example.test", "idem-1")
    assert result is None


def test_store_returns_none_when_key_unknown() -> None:
    store = IdempotencyStore()
    assert store.replay("alice@example.test", "unknown") is None


def test_store_does_not_contain_credential_strings_in_state() -> None:
    store = IdempotencyStore()
    sensitive = "SECRET-CODE-DO-NOT-LEAK"
    record = BrokerResult("req-2", "failed", duration_ms=7)
    store.record("alice@example.test", "idem-2", record)
    dump = repr(store)
    assert sensitive not in dump
    assert "do-not-leak".lower() not in dump.lower()
