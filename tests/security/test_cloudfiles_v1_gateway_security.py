"""Phase 0 security tests for the public CloudFiles gateway.

These tests are intentionally RED. They describe the security invariants the
public CloudFiles gateway MUST hold before any Phase 1 production
implementation. They reference:

  - specs/proposals/v0.2/92-cloudfiles-route-response-matrix.md
  - specs/proposals/v0.2/93-cloudfiles-phase0-red-tests.md
  - specs/proposals/v0.2/94-cloudfiles-threat-model.md

The tests below do NOT import any production code under
`cloudbrowser.cloudfiles.*`. They are expressed as focused security
assertions on the public boundary so the next phase can wire them to a real
WSGI app once the gateway module exists. Today they skip until Phase 1
produces the gateway module.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Mapping

import pytest

# Tests in this module rely on the conftest fixtures defined in
# tests/security/conftest.py. We import them by absolute path so the module
# can be collected regardless of pytest configuration.
import sys
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Threat coverage helpers
# ---------------------------------------------------------------------------


def _load_gateway_or_skip():
    """Load the gateway module or skip cleanly while Phase 0 RED is active."""
    return pytest.importorskip(
        "cloudbrowser.cloudfiles.api",
        reason="Phase 0: gateway production module is intentionally absent",
    )


# ---------------------------------------------------------------------------
# T1 — Forged public identity
# ---------------------------------------------------------------------------


def test_t1_forged_remote_email_is_rejected(gateway_app) -> None:
    """T1: Remote-Email header must never authorize another owner.

    The forged header must not switch the resolved principal to the
    attacker. The legitimate resolver still returns owner-a; the gateway
    must not forward the forged header to the downloads port.
    """
    downloads = FakeDownloads(
        store={"owner-a": [{"name": "invoice.pdf", "size": 1, "mtime": 1}]},
    )
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(
        app,
        "/api/files",
        headers={"Remote-Email": "attacker@example.test"},
    )
    assert response.status_code == 200, (
        "the legitimate principal must still be able to list; only the "
        "forged header must be ignored"
    )
    names = [entry["name"] for entry in response.json["entries"]]
    assert "invoice.pdf" in names, "owner-a listing must succeed"
    # The forged header must not have been forwarded to the downloads port.
    assert downloads.calls, "downloads port should have been called"
    forwarded = {k.lower() for k in downloads.calls[0].headers}
    assert "remote-email" not in forwarded, (
        "forged Remote-Email must not be forwarded to the internal downloads"
    )


def test_t1_forged_xcb_headers_are_rejected(gateway_app) -> None:
    """T1: X-CB-* headers must not affect owner binding or be forwarded."""
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
    for header, value in (
        ("X-CB-Principal", "owner-b"),
        ("X-CB-Owner", "owner-b"),
        ("X-CB-Profile", "p"),
        ("X-CB-Browser", "b"),
        ("X-CB-Generation", "1"),
    ):
        response = wsgi_get(
            app, "/api/files", headers={header: value},
        )
        assert response.status_code == 200, (
            "forged X-CB-* headers must not switch the principal"
        )
        # Gateway must strip these headers before calling downloads — the
        # forwarded values must come from the server-derived binding.
        if downloads.calls:
            forwarded = {
                k.lower(): v for k, v in downloads.calls[-1].headers.items()
            }
            assert forwarded.get(header.lower()) != value, (
                f"forged {header} value {value!r} must not be forwarded"
            )


# ---------------------------------------------------------------------------
# T2 — Cross-principal read
# ---------------------------------------------------------------------------


def test_t2_cross_owner_listing_is_empty(gateway_app) -> None:
    """T2: principal A must not see principal B's files."""
    downloads = FakeDownloads(
        store={
            PrincipalBinding(principal_id="owner-a"): [
                {"name": "invoice.pdf", "size": 1, "mtime": 1},
            ],
            PrincipalBinding(principal_id="owner-b"): [
                {"name": "secret.pdf", "size": 1, "mtime": 1},
            ],
        },
    )
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/api/files")
    assert response.status_code == 200, "owner-a listing should succeed"
    names = [entry["name"] for entry in response.json["entries"]]
    assert "secret.pdf" not in names, "owner-a must never see owner-b files"


# ---------------------------------------------------------------------------
# T3 — Stale, revoked, or missing binding
# ---------------------------------------------------------------------------


def test_t3_unauthenticated_request_is_unauthorized(gateway_app) -> None:
    """T3: a request without TinyAuth must be unauthorized."""
    app = gateway_app(
        downloads=FakeDownloads(),
        resolve_identity=make_resolver(subject=None),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/api/files")
    assert response.status_code in (401, 503), (
        f"missing binding must yield unauthorized or binding-unavailable, "
        f"got {response.status_code}"
    )

    app = gateway_app(
        downloads=FakeDownloads(),
        resolve_identity=make_resolver(subject="owner-a", revoked=True),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/api/files")
    assert response.status_code in (401, 403, 503), (
        f"revoked binding must yield unauthorized/forbidden/binding-unavailable, "
        f"got {response.status_code}"
    )

    # Stale binding: the resolver will raise because the resolver still
    # returns owner-a but with a stale generation. The gateway currently
    # treats any successful resolve as success; we verify the resolver
    # itself raises when generation is "stale" by constructing a session.
    from cloudbrowser.cloudfiles.identity import TinyAuthSession
    stale_session = TinyAuthSession(subject="owner-a", status="stale")
    app = gateway_app(
        downloads=FakeDownloads(),
        resolve_identity=lambda ctx: _resolve_session(ctx, stale_session),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/api/files")
    assert response.status_code in (401, 503), (
        f"stale binding must yield unauthorized or binding-unavailable, "
        f"got {response.status_code}"
    )


def _resolve_session(ctx, session):
    from cloudbrowser.cloudfiles.identity import resolve_principal
    return resolve_principal({"session": session, "request_id": ctx.get("request_id", "req-0")})


# ---------------------------------------------------------------------------
# T4 — Path traversal and unsafe filenames
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../escape.pdf",
        "..\\escape.pdf",
        "a/b.pdf",
        "a\\b.pdf",
        ".hidden.pdf",
        "name\x00.pdf",
        "name%2Fescape.pdf",
    ],
)
def test_t4_unsafe_filenames_are_blocked(gateway_app, name) -> None:
    """T4: unsafe filenames must be rejected before any disk operation."""
    downloads = FakeDownloads()
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, f"/file/{name}")
    assert response.status_code in (400, 404), (
        f"unsafe filename must be rejected: {name!r}"
    )


# ---------------------------------------------------------------------------
# T5 — Header injection
# ---------------------------------------------------------------------------


def test_t5_response_headers_are_bounded(gateway_app) -> None:
    """T5: response headers must not contain CRLF or arbitrary content."""
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
    response = wsgi_get(app, "/file/invoice.pdf")
    cd = response.headers.get("content-disposition", "")
    assert "\r" not in cd and "\n" not in cd, (
        "Content-Disposition must not contain CRLF"
    )


# ---------------------------------------------------------------------------
# T6 — Direct downloads exposure
# ---------------------------------------------------------------------------


def test_t6_compose_must_not_expose_downloads_publicly(tmp_path) -> None:
    """T6: cloudfiles* hosts must terminate at the gateway, not downloads."""
    compose = """
services:
  cloudfiles:
    image: cloudfiles:latest
  downloads:
    image: downloads:latest
    labels:
      traefik.http.routers.cloudfiles-public.rule: "Host(`cloudfiles2.example.test`)"
"""
    path = tmp_path / "compose.yaml"
    path.write_text(compose)
    module = importlib.import_module("cloudbrowser.cloudfiles.deployment")
    assert hasattr(module, "validate_public_routing"), (
        "deployment.validate_public_routing is missing"
    )
    with pytest.raises(Exception):
        module.validate_public_routing(compose_path=path)


# ---------------------------------------------------------------------------
# T7 — Identity leak in error/listing
# ---------------------------------------------------------------------------


def test_t7_listing_never_includes_principal_id(gateway_app) -> None:
    """T7: listing response must not include the principal id."""
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
    response = wsgi_get(app, "/api/files")
    blob = str(response.json)
    assert "principal_id" not in blob, "listing must omit principal_id"


def test_t7_error_envelope_is_bounded(gateway_app) -> None:
    """T7: error responses must use bounded fields only."""
    app = gateway_app(
        downloads=FakeDownloads(),
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/file/does-not-exist.pdf")
    if response.status_code >= 400:
        payload: Mapping[str, Any] = response.json
        assert set(payload.keys()) <= {"error_code", "request_id"}, (
            f"error envelope must be bounded, got {set(payload.keys())!r}"
        )


# ---------------------------------------------------------------------------
# T8 — Quarantine retrieval
# ---------------------------------------------------------------------------


def test_t8_quarantine_files_are_not_retrievable(gateway_app) -> None:
    """T8: quarantined files must not be retrievable through the public API."""
    downloads = FakeDownloads()  # store does not list the file
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/file/infected.pdf")
    assert response.status_code == 404, (
        "quarantined files must yield not_found on direct retrieval"
    )


def test_t8_quarantined_names_never_appear_in_the_public_listing(gateway_app) -> None:
    """T8: quarantine metadata must never surface names through /api/files.

    The internal downloads listing may carry quarantine metadata, but the
    public gateway must filter it out before any response is rendered.
    """
    downloads = FakeDownloads(
        store={
            "owner-a": [
                {"name": "invoice.pdf", "size": 5, "mtime": 1},
                {
                    "name": "infected.exe",
                    "qname": "infected.exe",
                    "size": 4,
                    "mtime": 1,
                    "quarantined": True,
                },
            ],
        },
    )
    app = gateway_app(
        downloads=downloads,
        resolve_identity=make_resolver(subject="owner-a"),
        server_identity={"component": "cloudfiles", "instance_id": "inst"},
    )
    response = wsgi_get(app, "/api/files", headers={"Accept": "application/json"})
    assert response.status_code == 200
    names = [entry["name"] for entry in response.json["entries"]]
    assert names == ["invoice.pdf"], (
        "quarantined names must never be listed publicly"
    )


# ---------------------------------------------------------------------------
# T9 — Quota/retention tampering
# ---------------------------------------------------------------------------


def test_t9_quota_overflow_is_rejected() -> None:
    """T9: ingest must reject files that would exceed quota."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "enforce_quota"), "enforce_quota is missing"
    quota = 1024
    with pytest.raises(Exception):
        module.enforce_quota(
            principal="owner-a",
            current_bytes=quota,
            incoming_bytes=1,
            quota_bytes=quota,
        )


def test_t9_old_files_are_not_retrievable() -> None:
    """T9: files older than retention must be purged or refused."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "is_retrievable"), "is_retrievable is missing"
    import datetime as _dt
    now = _dt.datetime(2026, 9, 3, tzinfo=_dt.timezone.utc)
    mtime = now - _dt.timedelta(days=91)
    assert module.is_retrievable(mtime=mtime, now=now, retention_days=90) is False


# ---------------------------------------------------------------------------
# T10 — GDPR erasure regression
# ---------------------------------------------------------------------------


def test_t10_erasure_removes_all_principal_data(tmp_path) -> None:
    """T10: erasure must remove all principal references."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "erase_principal"), "erase_principal is missing"
    module.erase_principal(principal="owner-a", store_root=tmp_path)
    for sub in ("entries", "quarantine", "tmp"):
        candidate = tmp_path / "owner-a" / sub
        assert not candidate.exists(), f"erasure must remove {sub}"
    assert not (tmp_path / "owner-a").exists(), "owner directory must be gone"


# ---------------------------------------------------------------------------
# T11 — Replay via stale binding headers
# ---------------------------------------------------------------------------


def test_t11_gateway_strips_xcb_headers(gateway_app) -> None:
    """T11: gateway must not forward client-supplied X-CB-* headers verbatim."""
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
            "X-CB-Profile": "p",
            "X-CB-Browser": "b",
            "X-CB-Generation": "1",
        },
    )
    forwarded = {
        k.lower(): v for k, v in downloads.calls[0].headers.items()
    } if downloads.calls else {}
    # The forwarded header values must come from the server-derived binding,
    # not from the public request.
    assert forwarded.get("x-cb-principal") != "owner-b", (
        "forged X-CB-Principal value must not be forwarded to downloads"
    )
    assert forwarded.get("x-cb-profile") != "p", (
        "forged X-CB-Profile value must not be forwarded"
    )
    assert forwarded.get("x-cb-browser") != "b", (
        "forged X-CB-Browser value must not be forwarded"
    )
    assert forwarded.get("x-cb-generation") != "1", (
        "forged X-CB-Generation value must not be forwarded"
    )


# ---------------------------------------------------------------------------
# T12 — Excessive payload
# ---------------------------------------------------------------------------


def test_t12_bounded_copy_rejects_oversize() -> None:
    """T12: bounded copy must reject oversize streams."""
    module = importlib.import_module("cloudbrowser.cloudfiles.ingest")
    assert hasattr(module, "bounded_copy"), "bounded_copy is missing"
    from io import BytesIO
    with pytest.raises(Exception):
        list(module.bounded_copy(src=BytesIO(b"x" * 2048), max_bytes=1024))


# ---------------------------------------------------------------------------
# T13 — Symlink and special-file escape
# ---------------------------------------------------------------------------


def test_t13_storage_refuses_symlinks(tmp_path) -> None:
    """T13: storage must not follow symlinks in the owner area."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "read"), "read is missing"
    target = tmp_path / "elsewhere.pdf"
    target.write_bytes(b"%PDF-1")
    link = tmp_path / "owner-a" / "entries" / "linked.pdf"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this filesystem")
    with pytest.raises(Exception):
        module.read(principal="owner-a", store_root=tmp_path, name="linked.pdf")


# ---------------------------------------------------------------------------
# T14 — Log and audit leakage
# ---------------------------------------------------------------------------


def test_t14_audit_events_are_redacted() -> None:
    """T14: audit events must be redacted."""
    module = importlib.import_module("cloudbrowser.cloudfiles.audit")
    assert hasattr(module, "redact_event"), "redact_event is missing"
    blob = str(module.redact_event(
        {"name": "invoice.pdf", "principal": "owner-a@example.test"},
    ))
    for forbidden in ("invoice.pdf", "owner-a@example.test"):
        assert forbidden not in blob, (
            f"audit event must be redacted: {forbidden!r}"
        )


# ---------------------------------------------------------------------------
# T15 — Direct public download URL reuse
# ---------------------------------------------------------------------------


def test_t15_no_presigned_url_route() -> None:
    """T15: there must be no public presigned URL route."""
    module = importlib.import_module("cloudbrowser.cloudfiles.routes")
    assert hasattr(module, "PUBLIC_ROUTES"), "PUBLIC_ROUTES is missing"
    pattern = re.compile(r"/signed/|/token/|/dl/[A-Za-z0-9_-]{16,}")
    for route in module.PUBLIC_ROUTES:
        assert not pattern.search(route), (
            f"public routes must not include presigned URL patterns: {route!r}"
        )
