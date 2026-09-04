"""Shared trusted edge-to-principal bridge for CloudFiles and Viewer."""

from __future__ import annotations

from typing import Mapping

from .api import SESSION_ENVIRON_KEY
from .contracts import OwnerBindingUnavailable, PrincipalBinding, Unauthorized
from .identity import TinyAuthSession, resolve_principal
from cloudbrowser.edge_auth import parse_edge_identity
from cloudbrowser.identity_links import IdentityLinkClient, IdentityLinkClientError


def _identity_environ_key(key: str) -> bool:
    upper = key.upper()
    return (
        upper.startswith("HTTP_REMOTE_")
        or upper.startswith("HTTP_X_CB_")
        or upper.startswith("HTTP_X_TINYAUTH_")
        or upper.startswith("HTTP_X_AUTH_REQUEST_")
    )


def resolve_tinyauth_session(context: Mapping[str, object]) -> PrincipalBinding:
    """Resolve only the server-injected, validated TinyAuth session."""
    session = context.get("session")
    if session is None:
        raise Unauthorized("TinyAuth session is missing")
    if not isinstance(session, TinyAuthSession):
        raise OwnerBindingUnavailable("TinyAuth session is invalid")
    return resolve_principal({"session": session})


def edge_session_middleware(app, *, identity_client: IdentityLinkClient):
    """Translate trusted forward-auth headers into one PMO-bound session."""
    if identity_client is None:
        raise ValueError("identity_client is required for edge authentication")

    def _wrap(environ, start_response):
        headers = {
            key.removeprefix("HTTP_").replace("_", "-"): value
            for key, value in environ.items()
            if key.startswith("HTTP_")
        }
        identity = parse_edge_identity(headers)
        principal = None
        if identity is not None:
            try:
                principal = identity_client.resolve(identity)
            except IdentityLinkClientError:
                principal = None
        for key in [key for key in environ if _identity_environ_key(key)]:
            del environ[key]
        if principal is not None:
            environ[SESSION_ENVIRON_KEY] = TinyAuthSession(subject=principal)
        else:
            environ.pop(SESSION_ENVIRON_KEY, None)
        return app(environ, start_response)

    return _wrap


__all__ = ["edge_session_middleware", "resolve_tinyauth_session"]
