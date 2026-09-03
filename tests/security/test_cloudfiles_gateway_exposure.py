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
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

# Load the shared test conftest by absolute path so the module can collect
# regardless of pytest's conftest discovery.
_CONFTEST_PATH = Path(__file__).resolve().parent / "conftest.py"
_SPEC = importlib.util.spec_from_file_location(  # type: ignore[attr-defined]
    "cloudfiles_test_conftest", _CONFTEST_PATH,
)
assert _SPEC and _SPEC.loader
_conftest = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("cloudfiles_test_conftest", _conftest)
_SPEC.loader.exec_module(_conftest)

FakeDownloads = _conftest.FakeDownloads
PrincipalBinding = _conftest.PrincipalBinding
make_resolver = _conftest.make_resolver
wsgi_get = _conftest.wsgi_get

pytestmark = pytest.mark.gateway


def _module(name: str):
    """Import a production module; the package must exist in Phase 1+."""
    return importlib.import_module(name)


def _gateway_module():
    return _module("cloudbrowser.cloudfiles.gateway")


# ---------------------------------------------------------------------------
# X1 — Direct downloads exposure through the public host
# ---------------------------------------------------------------------------


def test_public_route_table_never_aliases_internal_downloads_routes() -> None:
    """X1: PUBLIC_ROUTES must not proxy or alias downloads/v1 routes."""
    module = _gateway_module()
    public_routes = list(module.PUBLIC_ROUTES)
    forbidden = re.compile(
        r"^/(downloads|files|api/v1|v1)?(/api/files|/file/|/ready|/health)(/|$)",
        re.IGNORECASE,
    )
    for route in public_routes:
        assert not forbidden.search(route), (
            f"PUBLIC_ROUTES must not include aliased internal routes: {route!r}"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/downloads/api/files",
        "/downloads/file/x.pdf",
        "/downloads/health",
        "/api/v1/files",
        "/files/invoice.pdf",
        "/signed/abcd1234",
        "/token/abcd1234",
        "/dl/abcdefghijklmnop",
        "/internal/status",
        "/metrics",
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
        files={
            "owner-a": {"invoice.pdf": b"%PDF-1.4 hello"},
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
    internal_shape = wsgi_get(app, "/file/../../downloads/owner-b/secret.pdf")
    assert internal_shape.status_code in (400, 404), (
        "traversal-shaped names must be rejected before any file is served"
    )


# ---------------------------------------------------------------------------
# X2 — Unsafe/forged headers must never be forwarded to the internal service
# ---------------------------------------------------------------------------


def test_gateway_never_forwards_client_trusted_secret(gateway_app) -> None:
    """X2: a client-supplied X-CB-Trusted-Secret must never reach downloads."""
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
    wsgi_get(
        app,
        "/api/files",
        headers={"X-CB-Trusted-Secret": "forged-secret"},
    )
    forwarded = {
        k.lower() for k in downloads.calls[-1].headers
    } if downloads.calls else set()
    assert "x-cb-trusted-secret" not in forwarded, (
        "the gateway must strip any client-supplied X-CB-Trusted-Secret"
    )


def test_gateway_builds_internal_headers_but_never_forwards_client_ones(
    gateway_app,
) -> None:
    """X2: only the server-derived binding headers may reach downloads."""
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
    wsgi_get(
        app,
        "/api/files",
        headers={
            "X-CB-Principal": "owner-b",
            "X-CB-Profile": "fake",
            "X-CB-Browser": "fake",
            "X-CB-Generation": "999",
        },
    )
    forwarded = {
        k.lower(): v for k, v in downloads.calls[-1].headers.items()
    } if downloads.calls else {}
    # The value the gateway forwards must NOT match any client-supplied
    # forged value. The server-derived binding must arrive at downloads.
    assert forwarded.get("x-cb-principal") != "owner-b", (
        "forged X-CB-Principal value must not be forwarded to downloads"
    )
    assert forwarded.get("x-cb-profile") != "fake", (
        "forged X-CB-Profile value must not be forwarded"
    )
    assert forwarded.get("x-cb-browser") != "fake", (
        "forged X-CB-Browser value must not be forwarded"
    )
    assert forwarded.get("x-cb-generation") != "999", (
        "forged X-CB-Generation value must not be forwarded"
    )
    # The server-derived binding must arrive at downloads.
    for required in (
        "x-cb-principal",
        "x-cb-profile",
        "x-cb-browser",
        "x-cb-generation",
        "x-cb-request-id",
    ):
        assert required in forwarded, (
            f"server-derived binding header {required!r} must be set"
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
    """X1/X2: the gateway module must expose a validated route table."""
    module = _gateway_module()
    assert hasattr(module, "PUBLIC_ROUTES"), "PUBLIC_ROUTES is required"
    public_routes = list(module.PUBLIC_ROUTES)
    assert public_routes, "PUBLIC_ROUTES must contain at least /health"
    assert "/health" in public_routes
    assert "/" in public_routes
    assert "/api/files" in public_routes
    assert "/file/<name>" in public_routes
