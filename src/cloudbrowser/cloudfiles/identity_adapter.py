"""TinyAuth-compatible server identity adapter for CloudFiles.

The edge proxy performs authentication. This adapter consumes only a
server-injected opaque session subject and never trusts owner or principal
headers from the public request.
"""

from __future__ import annotations

from typing import Mapping

from .contracts import OwnerBindingUnavailable, PrincipalBinding, Unauthorized
from .identity import TinyAuthSession, resolve_principal


def resolve_tinyauth_session(context: Mapping[str, object]) -> PrincipalBinding:
    """Resolve a binding from the authenticated edge session context.

    The edge integration must place a validated ``TinyAuthSession`` in the
    context. A missing or malformed session fails closed; public headers are
    intentionally ignored by ``resolve_principal``.
    """

    session = context.get("session")
    if session is None:
        raise Unauthorized("TinyAuth session is missing")
    if not isinstance(session, TinyAuthSession):
        raise OwnerBindingUnavailable("TinyAuth session is invalid")
    return resolve_principal(dict(context))


__all__ = ["resolve_tinyauth_session"]
