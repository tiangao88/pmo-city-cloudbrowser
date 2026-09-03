"""Public CloudFiles gateway — header sanitization and internal bridge.

This module enforces threat T11 (replay via stale binding headers) and the
gateway-to-downloads boundary. The HTTP adapter lives in `api.py`.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from .contracts import PrincipalBinding
from .routes import PUBLIC_ROUTES, INTERNAL_DOWNLOADS_ROUTES


# Headers the public client may NEVER set or see forwarded. The gateway
# strips these on every incoming request and supplies a server-derived
# binding on every outgoing internal call.
INTERNAL_ONLY_HEADERS: frozenset[str] = frozenset({
    "remote-email",
    "x-cb-principal",
    "x-cb-owner",
    "x-cb-profile",
    "x-cb-browser",
    "x-cb-generation",
    "x-cb-trusted-secret",
    "x-cb-request-id",
})


# Headers that must never influence owner binding (T1).
IDENTITY_INFLUENCING_HEADERS: frozenset[str] = frozenset({
    "remote-email",
    "x-cb-principal",
    "x-cb-owner",
})


def sanitize_public_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Strip headers the public client may not influence.

    The remaining headers are passed through to the routing logic. The
    function returns a copy; the original mapping is not mutated.
    """

    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in INTERNAL_ONLY_HEADERS:
            continue
        cleaned[key] = value
    return cleaned


def build_internal_headers(
    *,
    binding: PrincipalBinding | Mapping[str, str],
    request_id: str,
) -> dict[str, str]:
    """Construct the headers the gateway sends to the internal downloads.

    Only the gateway may set X-CB-* headers; values come from the
    server-derived binding and the request_id, never from the public
    request.
    """

    if isinstance(binding, PrincipalBinding):
        mapping = {
            "principal_id": binding.principal_id,
            "profile_id": binding.profile_id,
            "browser_id": binding.browser_id,
            "generation": binding.generation,
        }
    else:
        mapping = dict(binding)
    if not request_id:
        raise ValueError("request_id must be non-empty")
    return {
        "X-CB-Principal": str(mapping["principal_id"]),
        "X-CB-Profile": str(mapping.get("profile_id", "profile-unassigned")),
        "X-CB-Browser": str(mapping.get("browser_id", "browser-unassigned")),
        "X-CB-Generation": str(mapping.get("generation", "generation-0")),
        "X-CB-Request-Id": request_id,
    }


def forbidden_forwarding_headers(headers: Iterable[str]) -> list[str]:
    """Return the subset of `headers` that must never be forwarded."""

    return [h for h in headers if h.lower() in INTERNAL_ONLY_HEADERS]


def within_size_budget(size: int, *, max_bytes: int) -> bool:
    """Return True if `size` is within the bounded response budget."""

    return 0 <= size <= max_bytes


__all__ = [
    "PUBLIC_ROUTES",
    "INTERNAL_DOWNLOADS_ROUTES",
    "INTERNAL_ONLY_HEADERS",
    "IDENTITY_INFLUENCING_HEADERS",
    "sanitize_public_headers",
    "build_internal_headers",
    "forbidden_forwarding_headers",
    "within_size_budget",
]
