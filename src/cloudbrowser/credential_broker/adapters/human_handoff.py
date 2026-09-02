"""Broker-side human MFA handoff (PRD-BR-06 chat-ask path).

The broker never stores, logs, or returns the human-supplied code. The
``HumanHandoffStore`` keeps only an opaque token bound to a single
(principal, site) pair. A submit consumes the token; subsequent submits,
mismatched principals, or unsupported modalities return a bounded status.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field


@dataclass(frozen=True)
class _Pending:
    principal_id: str
    site_id: str
    semantics: str = "totp"


class HumanHandoffStore:
    """In-memory broker handoff store. Single-use tokens."""

    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}

    def issue(self, *, principal_id: str, site_id: str) -> str:
        token = secrets.token_urlsafe(24)
        self._pending[token] = _Pending(principal_id=principal_id, site_id=site_id)
        return token

    def consume(self, *, token: str, principal_id: str) -> bool:
        pending = self._pending.pop(token, None)
        return pending is not None and pending.principal_id == principal_id


def human_handoff_request(
    store: HumanHandoffStore,
    *,
    principal_id: str,
    site_id: str,
) -> str:
    """Return an opaque token for one broker-mediated handoff."""

    return store.issue(principal_id=principal_id, site_id=site_id)


def human_handoff_submit(
    store: HumanHandoffStore,
    *,
    principal_id: str,
    token: str,
    code: str,
    modality: str = "totp",
) -> str:
    """Consume a handoff and return a bounded status string.

    Supported modalities in this release: TOTP only. Everything else is an
    explicit ``unsupported`` (no guess, no silent fallback).
    """

    if modality != "totp":
        return "unsupported"
    if not isinstance(code, str) or not code.strip():
        return "failed"
    return "authenticated" if store.consume(token=token, principal_id=principal_id) else "failed"
