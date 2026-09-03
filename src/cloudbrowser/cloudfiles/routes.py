"""Public route table for the CloudFiles gateway.

Threat T15 requires that there is no presigned URL route. The route table is
the single source of truth for what the public host can serve.
"""

from __future__ import annotations

import re


# Public routes — bounded set, no presigned URLs, no path traversal.
PUBLIC_ROUTES = (
    "/health",
    "/ready",
    "/",
    "/api/files",
    "/file/<name>",
)


# Internal routes that must NEVER be reachable from the public host.
INTERNAL_DOWNLOADS_ROUTES = (
    "/downloads/health",
    "/downloads/ready",
    "/downloads/api/files",
    "/downloads/file/<name>",
)


def public_route_count() -> int:
    """Return the count of public routes. Used by deployment validators."""

    return len(PUBLIC_ROUTES)


def is_internal_route(path: str) -> bool:
    """Return True if `path` matches an internal downloads route."""

    for pattern in INTERNAL_DOWNLOADS_ROUTES:
        regex = _to_regex(pattern)
        if regex.fullmatch(path):
            return True
    return False


def _to_regex(pattern: str) -> "re.Pattern[str]":
    parts = []
    for segment in pattern.split("/"):
        if segment == "<name>":
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(segment))
    return re.compile("/".join(parts))


__all__ = [
    "PUBLIC_ROUTES",
    "INTERNAL_DOWNLOADS_ROUTES",
    "is_internal_route",
    "public_route_count",
]
