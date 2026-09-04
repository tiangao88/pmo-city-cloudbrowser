"""Public CloudFiles gateway package.

This package implements the public CloudFiles product surface defined in
`specs/contracts/cloudfiles/v1/README.md` and the frozen target in
`specs/proposals/v0.2/89-cloudfiles-product-requirement.md`.

Boundary invariants live in `tests/contract/test_cloudfiles_v1_gateway_boundary.py`
and `tests/security/test_cloudfiles_v1_gateway_security.py`. Every public
symbol added here must keep those tests green.
"""

from __future__ import annotations

__all__ = [
    "contracts",
    "identity",
    "filenames",
    "errors",
    "store",
    "policy",
    "audit",
    "ingest",
    "headers",
    "routes",
    "deployment",
    "gateway",
    "api",
    "templates",
    "runtime",
    "service",
    "identity_adapter",
    "downloads_client",
    "downloads_adapter",
    "browser_downloads",
    "phase2",
    "scanner",
    "retention",
    "quarantine",
    "erasure",
    "metrics",
]

__version__ = "0.2.0-phase3"
