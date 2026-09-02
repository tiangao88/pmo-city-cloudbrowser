"""Single-use, TTL-bound human MFA handoff for the broker."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class _Pending:
    principal_id: str
    site_id: str
    generation: str | None
    issued_at: float


class HumanHandoffStore:
    """In-memory challenge store that never stores the human code."""

    def __init__(self, *, clock: Callable[[], float] | None = None, ttl_seconds: float = 180.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("handoff TTL must be positive")
        self._clock = clock or time.monotonic
        self._ttl_seconds = float(ttl_seconds)
        self._pending: dict[str, _Pending] = {}

    def __repr__(self) -> str:
        # Do not expose token, principal, or any future challenge payload in
        # diagnostic output. Only an operational count is safe.
        return f"HumanHandoffStore(pending_count={len(self._pending)})"

    def issue(self, *, principal_id: str, site_id: str, generation: str | None = None) -> str:
        token = secrets.token_urlsafe(24)
        self._pending[token] = _Pending(
            principal_id=principal_id,
            site_id=site_id,
            generation=generation,
            issued_at=float(self._clock()),
        )
        return token

    def consume(
        self,
        *,
        token: str,
        principal_id: str,
        site_id: str | None = None,
        generation: str | None = None,
        verify_code: Callable[[str], bool] | None = None,
        code: str = "",
    ) -> bool:
        pending = self._pending.get(token)
        if pending is None:
            return False
        if float(self._clock()) - pending.issued_at > self._ttl_seconds:
            self._pending.pop(token, None)
            return False
        # A mismatched caller must not be able to burn the valid challenge.
        if pending.principal_id != principal_id:
            return False
        if site_id is not None and pending.site_id != site_id:
            return False
        if generation is not None and pending.generation != generation:
            return False

        # Consume after binding validation, before calling the verifier. The
        # verifier receives the code only in this call and the store retains
        # neither the code nor the result.
        self._pending.pop(token, None)
        verifier = verify_code or (lambda supplied: bool(supplied.strip()))
        try:
            return bool(verifier(code))
        except Exception:
            return False


def human_handoff_request(
    store: HumanHandoffStore,
    *,
    principal_id: str,
    site_id: str,
    generation: str | None = None,
) -> str:
    """Issue one opaque challenge-bound handoff token."""

    return store.issue(principal_id=principal_id, site_id=site_id, generation=generation)


def human_handoff_submit(
    store: HumanHandoffStore,
    *,
    principal_id: str,
    token: str,
    code: str,
    modality: str = "totp",
    site_id: str | None = None,
    generation: str | None = None,
    verify_code: Callable[[str], bool] | None = None,
) -> str:
    """Consume a handoff and return only ``authenticated``/``failed``/``unsupported``."""

    if modality != "totp":
        return "unsupported"
    if not isinstance(code, str) or not code.strip():
        return "failed"
    return (
        "authenticated"
        if store.consume(
            token=token,
            principal_id=principal_id,
            site_id=site_id,
            generation=generation,
            verify_code=verify_code,
            code=code,
        )
        else "failed"
    )


__all__ = ["HumanHandoffStore", "human_handoff_request", "human_handoff_submit"]
