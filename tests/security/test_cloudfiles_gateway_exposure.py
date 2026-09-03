"""Phase 0 focused RED tests: direct downloads exposure and unsafe headers.

These tests target the *public gateway HTTP boundary* from the frozen
CloudFiles target (specs/proposals/v0.2/89-cloudfiles-product-requirement.md)
and the public contract (specs/contracts/cloudfiles/v1/README.md):

- X1 — public-host exposure: no public route may proxy, alias, or reach the
  internal downloads container or its routes; the downloads service is never
  a public target (requirement §1, §6 and matrix `92-...` internal table).
- X2 — unsafe/forged header forwarding: client-supplied binding, owner, or
  shared-secret headers must never be forwarded to the internal downloads
  service or influence the server-derived binding (requirement §3, threat
  model T1/T6/T11).

The production modules `cloudbrowser.cloudfiles.gateway` and
`cloudbrowser.cloudfiles.api` do NOT exist yet. Like the contract-boundary
slice (`tests/contract/test_cloudfiles_v1_gateway_boundary.py`), this module
loads them at test time via ``importlib`` so every test fails with
`ModuleNotFoundError` while collection stays clean — the intended Phase-0 RED
signal. When Phase 1+ introduces the modules, the same tests exercise the real
gateway via the shared WSGI harness in `tests/security/conftest.py`.
"""

from __future__ import annotations

import importlib
import re

import pytest

from cloudfiles_test_conftest import (  # type: ignore[import-not-found]
    FakeDownloads,
    PrincipalBinding,
    make_resolver,
    wsgi_get,
)

pytestmark = pytest.mark.gateway


def _module(name: str):
    """Import a production module; RED until the cloudfiles package exists."""
    return importlib.import_module(name)


def _gateway_module():
    return _module("cloudbrowser.cloudfiles.gateway")


# ---------------------------------------------------------------------------
# X1 — Direct downloads exposure through the public host
# ---------------------------------------------------------------------------


def test_public_route_table_never_aliases_internal_downloads_routes() -> None:
    """X1: PUBLIC_ROUTES must not proxy or alias downloads/v1 routes."""
    module = _gateway_module()
    public_routes = module.PUBLIC_ROUTES
    forbidden = re.compile(
        r"^/(downloads|files|api/v1|v1)?(/api/files|/file/|/ready|/health)(/|$)",
        re.IGNORECASE,
    )
    for route in public_routes:
        assert not forbidden.search(route), (
            f"public route must not alias an internal downloads route: {route!r}"
        )
    assert "/api/files" in public_routes, "the owned public listing route is missing"
    assert "/health" in public_routes, "the bounded health route is missing"


@pytest.mark.parametrize(
    "path",
    [
        "/downloads/api/files",      # direct downloads listing via public host
        "/downloads/file/x.pdf",     # direct downloads file via public host
        "/downloads/health",         # direct downloads health via public host
        "/api/v1/files",             # versioned alias of the internal contract
        "/files/invoice.pdf",        # slot-style alias
        "/signed/abcd1234",          # presigned-style token route
        "/token/abcd1234",           # token route
        "/dl/abcdefghijklmnop",      # short-link route
        "/internal/status",          # internal surface
        "/metrics",                  # internal metrics
    ],
)
def test_public_host_rejects_internal_downloads_paths(gateway_app, path: str) -> None:
    """X1: requests for internal downloads paths on the public host must 404."""
    downloads = FakeDownloads()
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, path)
    assert response.status_code == 404, (
        f"internal path {path!r} must not be servable on the public host"
    )
    assert downloads.calls == [], (
        f"internal downloads must never be reached for public path {path!r}"
    )


def test_public_file_route_serves_only_via_server_bound_listing(gateway_app) -> None:
    """X1: /file/<name> must resolve through the owner-bound entry, never a
    raw internal path or a guessed downloads path."""
    downloads = FakeDownloads(
        store={
            PrincipalBinding(principal_id="owner-a"): [
                {"name": "invoice.pdf", "size": 1, "mtime": 1},
            ],
        },
    )
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    ok = wsgi_get(app, "/file/invoice.pdf")
    assert ok.status_code == 200, "owner-bound file must be retrievable"
    assert ok.headers.get("content-disposition", "").startswith("attachment"), (
        "file responses must be attachment-only"
    )
    # A name that exists in the fake store but under another namespace shape
    # must not resolve through the raw internal path. The exact status is
    # contract-flexible (invalid_name or not_found); exposure is not.
    internal_shape = wsgi_get(app, "/file/../../downloads/owner-b/secret.pdf")
    assert internal_shape.status_code in (400, 404), (
        "traversal-shaped names must be rejected before any file is served"
    )


# ---------------------------------------------------------------------------
# X2 — Unsafe/forged headers must never be forwarded to the internal service
# ---------------------------------------------------------------------------


def test_gateway_never_forwards_client_trusted_secret(gateway_app) -> None:
    """X2: a client-supplied X-CB-Trusted-Secret must never reach downloads.

    The internal shared secret is gateway-side configuration only. The public
    request may carry it; the gateway must strip it and use only its own
    configured value.
    """
    downloads = FakeDownloads(
        store={
            PrincipalBinding(principal_id="owner-a"): [
                {"name": "invoice.pdf", "size": 1, "mtime": 1},
            ],
        },
    )
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(
        app,
        "/api/files",
        headers={"X-CB-Trusted-Secret": "client-forged-secret"},
    )
    assert response.status_code == 200, "owner-a listing must still succeed"
    assert downloads.calls, "the gateway must call the internal downloads port"
    forwarded = downloads.calls[0].headers
    assert "X-CB-Trusted-Secret" not in forwarded, (
        "client-supplied trusted secret must not be forwarded to downloads"
    )


def test_gateway_builds_internal_headers_but_never_forwards_client_ones(
    gateway_app,
) -> None:
    """X2: only the server-derived binding headers may reach downloads.

    build_internal_headers derives binding headers from the resolved
    principal and a fresh gateway request ID; none of the client-supplied
    values may appear in what the gateway forwards.
    """
    module = _gateway_module()
    binding = PrincipalBinding(principal_id="owner-a", generation="generation-1")
    internal = module.build_internal_headers(
        binding={"principal_id": binding.principal_id, "generation": binding.generation},
        request_id="req-gateway-1",
    )
    assert internal["X-CB-Principal"] == "owner-a"
    assert internal["X-CB-Generation"] == "generation-1"

    downloads = FakeDownloads(
        store={
            binding: [
                {"name": "invoice.pdf", "size": 1, "mtime": 1},
            ],
        },
    )
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a", generation="generation-1"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    wsgi_get(
        app,
        "/api/files",
        headers={
            "X-CB-Principal": "owner-b",
            "X-CB-Profile": "forged-profile",
            "X-CB-Browser": "forged-browser",
            "X-CB-Generation": "forged-generation",
            "X-CB-Request-Id": "forged-request",
        },
    )
    assert downloads.calls, "the gateway must call the internal downloads port"
    forwarded = downloads.calls[0].headers
    assert forwarded["X-CB-Principal"] == "owner-a", (
        "forged X-CB-Principal must not be forwarded"
    )
    assert forwarded["X-CB-Generation"] == "generation-1", (
        "forged X-CB-Generation must not be forwarded"
    )
    assert forwarded.get("X-CB-Request-Id") != "forged-request", (
        "client-supplied request id must not be forwarded"
    )


def test_sanitize_public_headers_strips_internal_and_forbidden_headers() -> None:
    """X2: sanitization drops every header the public client may not set."""
    module = _gateway_module()
    cleaned = module.sanitize_public_headers(
        {
            "Remote-Email": "attacker@example.test",
            "X-CB-Principal": "owner-b",
            "X-CB-Trusted-Secret": "forged",
            "X-CB-Profile": "p",
            "X-CB-Browser": "b",
            "X-CB-Generation": "1",
            "Accept": "text/html",
        }
    )
    lowered = {k.lower() for k in cleaned}
    assert "remote-email" not in lowered, "Remote-Email must be stripped"
    assert not any(k.startswith("x-cb-") for k in lowered), (
        "all X-CB-* headers must be stripped"
    )
    assert "accept" in lowered, "harmless client headers may pass through"


def test_public_error_envelope_never_echoes_request_headers(gateway_app) -> None:
    """X2: error bodies are bounded and never echo raw request headers."""
    app = gateway_app(
        downloads=FakeDownloads(),
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(
        app,
        "/file/not-there.pdf",
        headers={"Remote-Email": "attacker@example.test"},
    )
    if response.status_code >= 400:
        payload = response.json
        assert set(payload.keys()) <= {"error_code", "request_id"}, (
            f"error envelope must be bounded, got {sorted(payload)}"
        )
        blob = str(payload)
        assert "attacker@example.test" not in blob, (
            "error must not echo the raw Remote-Email header"
        )


def test_gateway_module_exposes_the_bounded_route_table() -> None:
    """X1/X2: the gateway module must expose a validated route table.

    Static check that keeps the sibling threat list honest (no presigned or
    signed download routes exist on the public surface).
    """
    # Also asserts the public API factory surface exists (RED until then).
    api = importlib.import_module("cloudbrowser.cloudfiles.api")
    assert callable(getattr(api, "create_cloudfiles_app", None)), (
        "cloudbrowser.cloudfiles.api must expose create_cloudfiles_app"
    )
    module = _gateway_module()
    public_routes = module.PUBLIC_ROUTES
    signed = re.compile(r"/signed/|/token/|/dl/[A-Za-z0-9_-]{16,}")
    for route in public_routes:
        assert not signed.search(route), (
            f"public route must not be presigned/signed: {route!r}"
        )
    assert "/file/<name>" in public_routes or any(
        r.startswith("/file/") for r in public_routes
    ), "the attachment route must be present in the public route table"