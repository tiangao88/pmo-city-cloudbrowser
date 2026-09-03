"""Server-derived principal binding for the public CloudFiles gateway.

This module enforces Threat T1 (forged identity) and Threat T3 (stale,
revoked, or missing bindings). It deliberately trusts only the TinyAuth
session supplied via the `Authorization` header. Client-supplied headers
(`Remote-Email`, `X-CB-*`, query-string `?owner=`) MUST NOT influence the
binding.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .contracts import (
    CloudFilesError,
    Forbidden,
    OwnerBindingUnavailable,
    PrincipalBinding,
    Unauthorized,
)


@dataclass(frozen=True)
class TinyAuthSession:
    """A validated TinyAuth session resolved by the gateway.

    The session is constructed by the production identity resolver that
    integrates with the TinyAuth provider. Tests construct it directly with
    a principal or a deliberate failure mode.
    """

    subject: str | None
    status: str = "active"  # active | revoked | stale | missing
    generation: str = "generation-0"
    profile_id: str = "profile-unassigned"
    browser_id: str = "browser-unassigned"
    request_id: str = "req-0"

    def __post_init__(self) -> None:
        if self.status not in {"active", "revoked", "stale", "missing"}:
            raise ValueError("status must be active, revoked, stale, or missing")
        if self.subject is None and self.status != "missing":
            raise ValueError("subject is required for active/revoked/stale sessions")
        if self.subject is not None and not _PRINCIPAL.fullmatch(self.subject):
            raise ValueError("subject must be a bounded non-PII string")


_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:+-]{0,255}$")
_FORBIDDEN_HEADERS = {
    "remote-email",
    "x-cb-principal",
    "x-cb-owner",
    "x-cb-profile",
    "x-cb-browser",
    "x-cb-generation",
    "x-cb-trusted-secret",
    "x-cb-request-id",
}


def _extract_session(context: dict) -> TinyAuthSession:
    """Extract a validated session from the request context.

    The session is the only authority. Headers such as `Remote-Email` and
    `X-CB-*` are ignored — that is the security invariant T1.
    """

    session = context.get("session")
    if session is None:
        # Build a deliberate missing session so the resolver can fail closed.
        return TinyAuthSession(subject=None, status="missing",
                                request_id=str(context.get("request_id", "req-0")))
    if not isinstance(session, TinyAuthSession):
        raise OwnerBindingUnavailable("session is not a TinyAuthSession")
    return session


def resolve_principal(context: dict) -> PrincipalBinding:
    """Resolve the server-bound principal for the request.

    Returns a `PrincipalBinding` only when the session is `active`. Any other
    status (missing, revoked, stale) raises the appropriate error so the
    caller fails closed.

    The function deliberately does not look at `headers`, `query`, or `body`
    for identity; that is the whole point of the threat model T1.
    """

    session = _extract_session(context)
    if session.status == "missing":
        raise Unauthorized("TinyAuth session is missing")
    if session.status == "revoked":
        raise Forbidden("TinyAuth session has been revoked")
    if session.status == "stale":
        raise OwnerBindingUnavailable("TinyAuth session is stale")
    if not session.subject:
        raise OwnerBindingUnavailable("TinyAuth session has no subject")
    return PrincipalBinding(
        principal_id=session.subject,
        profile_id=session.profile_id,
        browser_id=session.browser_id,
        generation=session.generation,
        request_id=session.request_id,
    )


def hash_principal(principal_id: str) -> str:
    """Return a stable non-PII hash of the principal identifier.

    Used for log correlation without exposing the raw identifier.
    """

    if not isinstance(principal_id, str) or not _PRINCIPAL.fullmatch(principal_id):
        raise ValueError("principal_id must be bounded non-PII text")
    return hashlib.sha256(principal_id.encode("utf-8")).hexdigest()


def public_principal_id(binding: PrincipalBinding) -> str:
    """Return the hash of the principal id for use in logs and audit events."""

    return hash_principal(binding.principal_id)


__all__ = [
    "TinyAuthSession",
    "resolve_principal",
    "hash_principal",
    "public_principal_id",
    "Unauthorized",
    "Forbidden",
    "OwnerBindingUnavailable",
    "CloudFilesError",
    "PrincipalBinding",
    "FORBIDDEN_HEADERS",
]
