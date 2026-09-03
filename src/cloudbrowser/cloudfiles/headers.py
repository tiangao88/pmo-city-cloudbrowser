"""Bounded response-header construction for the public CloudFiles gateway.

Threat T5 requires that Content-Disposition and other response headers never
contain CRLF or arbitrary content. This module provides typed header
construction.
"""

from __future__ import annotations

from typing import Mapping

from .filenames import safe_content_disposition


# Allowlisted content types for the public gateway.
_ALLOWED_TYPES = {
    "application/pdf",
    "application/json",
    "application/octet-stream",
    "text/html",
    "text/plain",
    "image/png",
    "image/jpeg",
}


def bake_response_headers(
    *,
    filename: str,
    content_type: str = "application/octet-stream",
    status: int = 200,
    cache: str = "no-store",
) -> dict[str, str]:
    """Build the bounded response headers for a public file response."""

    if not isinstance(filename, str) or not filename:
        raise ValueError("filename must be a non-empty string")
    if content_type not in _ALLOWED_TYPES:
        raise ValueError(f"content_type must be allowlisted, got {content_type!r}")
    if status < 100 or status > 599:
        raise ValueError("status must be a valid HTTP status code")
    if cache not in {"no-store", "no-cache", "private"}:
        raise ValueError("cache must be no-store, no-cache, or private")
    headers = {
        "Content-Type": content_type,
        "Content-Disposition": safe_content_disposition(filename),
        "Cache-Control": cache,
        "Referrer-Policy": "no-referrer",
        "Server": "cloudfiles",
    }
    return headers


def within_size_budget(size: int, *, max_bytes: int) -> bool:
    """Return True if `size` is within the bounded response budget."""

    return 0 <= size <= max_bytes


__all__ = [
    "bake_response_headers",
    "within_size_budget",
]
