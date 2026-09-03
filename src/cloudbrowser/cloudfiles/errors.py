"""Bounded error envelopes for the public CloudFiles gateway.

Threat T7 requires that public error responses never echo raw identity,
paths, or headers. This module builds the bounded envelope and maps internal
exceptions to public error codes.
"""

from __future__ import annotations

from .contracts import (
    CloudFilesError,
    DependencyUnavailable,
    Forbidden,
    InvalidName,
    NotFound,
    OwnerBindingUnavailable,
    OwnerMismatch,
    TooLarge,
    Unauthorized,
)


_CODE_BY_ERROR = {
    Unauthorized: "unauthorized",
    Forbidden: "forbidden",
    OwnerBindingUnavailable: "owner_binding_unavailable",
    OwnerMismatch: "forbidden_owner_mismatch",
    InvalidName: "invalid_name",
    NotFound: "not_found",
    TooLarge: "too_large",
    DependencyUnavailable: "dependency_unavailable",
}


def build_error(code: str, request_id: str) -> dict[str, str]:
    """Build the bounded public error envelope.

    Only `error_code` and `request_id` are emitted. The caller must never
    pass raw identifiers, paths, or headers.
    """

    if not isinstance(code, str) or not code:
        raise ValueError("error code must be a non-empty string")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id must be a non-empty string")
    return {"error_code": code, "request_id": request_id}


def public_code_for(exc: BaseException) -> str:
    """Map an internal exception to a bounded public error code."""

    if type(exc) in _CODE_BY_ERROR:
        return _CODE_BY_ERROR[type(exc)]
    if isinstance(exc, CloudFilesError):
        return "internal_error"
    return "internal_error"


__all__ = [
    "build_error",
    "public_code_for",
]
