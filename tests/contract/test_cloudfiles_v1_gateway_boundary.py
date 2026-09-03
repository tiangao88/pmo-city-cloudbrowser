"""Phase 0 contract tests for the public CloudFiles gateway boundary.

These tests are intentionally RED. They describe the boundary the public
CloudFiles gateway MUST hold before any Phase 1 production implementation.
They reference:

  - specs/proposals/v0.2/92-cloudfiles-route-response-matrix.md
  - specs/proposals/v0.2/93-cloudfiles-phase0-red-tests.md
  - specs/proposals/v0.2/94-cloudfiles-threat-model.md

This file uses direct import assertions on
``cloudbrowser.cloudfiles.*`` modules, which do not yet exist. The tests are
collected and error at import time. That is the intended Phase-0 RED signal
for the boundary invariant suite. After Phase 1 introduces the production
modules, every test in this file must pass.
"""

from __future__ import annotations

import importlib
import re
from typing import Mapping

import pytest


# ---------------------------------------------------------------------------
# T1 — Forged public identity
# ---------------------------------------------------------------------------


def test_remote_email_header_is_not_authoritative() -> None:
    """T1: Remote-Email must not influence the server-bound principal."""
    module = importlib.import_module("cloudbrowser.cloudfiles.identity")
    resolver = getattr(module, "resolve_principal", None)
    assert resolver is not None, "resolve_principal is missing"
    ctx = {"headers": {"Remote-Email": "victim@example.test"}}
    principal = resolver(ctx)
    assert principal != "victim@example.test", (
        "Remote-Email must not be authoritative; identity must be "
        "server-derived from TinyAuth session"
    )


def test_xcb_principal_header_is_not_authoritative() -> None:
    """T1: X-CB-Principal must not influence the server-bound principal."""
    module = importlib.import_module("cloudbrowser.cloudfiles.identity")
    resolver = getattr(module, "resolve_principal", None)
    assert resolver is not None, "resolve_principal is missing"
    ctx = {"headers": {"X-CB-Principal": "owner-b"}}
    principal = resolver(ctx)
    assert principal != "owner-b", (
        "X-CB-Principal must not be authoritative"
    )


def test_query_string_owner_is_not_authoritative() -> None:
    """T1: ?owner=<other> must not select another principal."""
    module = importlib.import_module("cloudbrowser.cloudfiles.identity")
    resolver = getattr(module, "resolve_principal", None)
    assert resolver is not None, "resolve_principal is missing"
    ctx = {"headers": {}, "query": {"owner": "owner-b"}}
    principal = resolver(ctx)
    assert principal != "owner-b", "Query string must not be authoritative"


# ---------------------------------------------------------------------------
# T2 — Cross-principal read
# ---------------------------------------------------------------------------


def test_storage_paths_are_rooted_under_server_bound_principal(tmp_path) -> None:
    """T2: store must refuse any path that escapes the server-bound owner."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "resolve_safe_path"), "resolve_safe_path is missing"
    with pytest.raises(Exception):
        module.resolve_safe_path(
            principal="owner-a",
            store_root=tmp_path,
            name="../owner-b/secret.pdf",
        )


def test_listing_for_principal_a_excludes_principal_b_files(tmp_path) -> None:
    """T2: principal A listing must never include principal B's entries."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "list_entries"), "list_entries is missing"
    entries_a = module.list_entries(principal="owner-a", store_root=tmp_path)
    entries_b = module.list_entries(principal="owner-b", store_root=tmp_path)
    assert not (set(entries_a) & set(entries_b)), (
        "Listings from different principals must never overlap"
    )


def test_reading_principal_b_file_from_principal_a_is_rejected(tmp_path) -> None:
    """T2: a read with a name escaping owner-a must be rejected."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "read"), "read is missing"
    with pytest.raises(Exception):
        module.read(
            principal="owner-a",
            store_root=tmp_path,
            name="../owner-b/secret.pdf",
        )


# ---------------------------------------------------------------------------
# T3 — Stale, revoked, or missing binding
# ---------------------------------------------------------------------------


def test_missing_binding_returns_owner_binding_unavailable() -> None:
    """T3: a request with no server-bound identity must fail closed."""
    module = importlib.import_module("cloudbrowser.cloudfiles.identity")
    resolver = getattr(module, "resolve_principal", None)
    assert resolver is not None, "resolve_principal is missing"
    with pytest.raises(Exception):
        resolver({"headers": {}, "session": None})


def test_revoked_binding_returns_owner_binding_unavailable() -> None:
    """T3: a revoked session must not yield a principal."""
    module = importlib.import_module("cloudbrowser.cloudfiles.identity")
    resolver = getattr(module, "resolve_principal", None)
    assert resolver is not None, "resolve_principal is missing"
    with pytest.raises(Exception):
        resolver({"headers": {}, "session": {"status": "revoked"}})


def test_stale_binding_returns_owner_binding_unavailable() -> None:
    """T3: a stale session must not yield a principal."""
    module = importlib.import_module("cloudbrowser.cloudfiles.identity")
    resolver = getattr(module, "resolve_principal", None)
    assert resolver is not None, "resolve_principal is missing"
    with pytest.raises(Exception):
        resolver({"headers": {}, "session": {"status": "stale"}})


# ---------------------------------------------------------------------------
# T4 — Path traversal and unsafe filenames
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../escape.pdf",
        "..\\escape.pdf",
        "a/b",
        ".hidden",
        "name\x00.pdf",
        "name%0A.pdf",
        "name\r.pdf",
    ],
)
def test_unsafe_filename_is_rejected(name: str) -> None:
    """T4: unsafe filenames must be rejected by the policy."""
    module = importlib.import_module("cloudbrowser.cloudfiles.filenames")
    assert hasattr(module, "validate_name"), "validate_name is missing"
    result = module.validate_name(name)
    assert result is None, f"unsafe filename must be rejected: {name!r}"


# ---------------------------------------------------------------------------
# T5 — Header injection
# ---------------------------------------------------------------------------


def test_filename_with_crlf_is_rejected_before_header_written() -> None:
    """T5: filenames with CRLF must be rejected before any header is set."""
    module = importlib.import_module("cloudbrowser.cloudfiles.filenames")
    assert hasattr(module, "safe_content_disposition"), (
        "safe_content_disposition is missing"
    )
    with pytest.raises(Exception):
        module.safe_content_disposition('name\r\nX-Injected: 1.pdf')


def test_filename_with_quote_is_handled_safely() -> None:
    """T5: filenames with quotes must produce a safely escaped header."""
    module = importlib.import_module("cloudbrowser.cloudfiles.filenames")
    assert hasattr(module, "safe_content_disposition"), (
        "safe_content_disposition is missing"
    )
    header = module.safe_content_disposition('na"me.pdf')
    assert "\"" not in re.sub(r'filename="[^"]+"', "", header), (
        "quotes inside filename must be escaped or rejected"
    )


# ---------------------------------------------------------------------------
# T6 — Direct downloads exposure
# ---------------------------------------------------------------------------


def test_compose_does_not_route_public_host_to_downloads_container(tmp_path) -> None:
    """T6: cloudfiles* hosts must terminate at the gateway, not downloads."""
    compose = """
services:
  cloudfiles:
    image: cloudfiles:latest
    expose: ["8084"]
  downloads:
    image: downloads:latest
    expose: ["8083"]
"""
    path = tmp_path / "compose.yaml"
    path.write_text(compose)
    module = importlib.import_module("cloudbrowser.cloudfiles.deployment")
    assert hasattr(module, "public_hosts"), "deployment.public_hosts is required"
    hosts = module.public_hosts(compose_path=path)
    assert all(h.get("target_service") != "downloads" for h in hosts), (
        "no public host may target the downloads container"
    )


# ---------------------------------------------------------------------------
# T7 — Identity leak in error/listing
# ---------------------------------------------------------------------------


def test_health_response_omits_identity() -> None:
    """T7: /health response must not include any identity strings."""
    module = importlib.import_module("cloudbrowser.cloudfiles.api")
    assert hasattr(module, "build_health_response"), (
        "api.build_health_response is missing"
    )
    payload = module.build_health_response()
    blob = str(payload)
    for forbidden in ("@", "owner-", "principal_id", "path", "/data"):
        assert forbidden not in blob, (
            f"health response must not leak identity strings ({forbidden!r})"
        )


def test_listing_response_omits_principal_id_and_paths() -> None:
    """T7: /api/files response must not include principal_id or paths."""
    module = importlib.import_module("cloudbrowser.cloudfiles.api")
    assert hasattr(module, "build_listing_response"), (
        "api.build_listing_response is missing"
    )
    response = module.build_listing_response(
        entries=[{"name": "invoice.pdf", "size": 1, "mtime": 1}],
    )
    blob = str(response)
    assert "principal_id" not in blob, "listing must not include principal_id"
    assert "path" not in blob, "listing must not include path"


def test_error_envelope_uses_bounded_error_code_and_request_id() -> None:
    """T7: errors must be bounded (error_code + request_id only)."""
    module = importlib.import_module("cloudbrowser.cloudfiles.errors")
    assert hasattr(module, "build_error"), "errors.build_error is missing"
    payload = module.build_error(code="invalid_name", request_id="req-1")
    assert set(payload.keys()) == {"error_code", "request_id"}, (
        "error envelope keys must be exactly error_code and request_id"
    )


# ---------------------------------------------------------------------------
# T8 — Quarantine retrieval
# ---------------------------------------------------------------------------


def test_quarantined_files_are_not_listed(tmp_path) -> None:
    """T8: quarantined files must not appear in the retrievable listing."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "list_entries"), "list_entries is missing"
    listing = module.list_entries(principal="owner-a", store_root=tmp_path)
    assert "infected.pdf" not in listing, "quarantined files must not be listed"


def test_direct_read_of_quarantined_name_returns_not_found(tmp_path) -> None:
    """T8: direct read of a quarantined name must fail with not_found."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "read"), "read is missing"
    result = module.read(
        principal="owner-a", store_root=tmp_path, name="infected.pdf",
    )
    assert result is None or result == b"", (
        "quarantined files must not be retrievable"
    )


# ---------------------------------------------------------------------------
# T9 — Quota/retention tampering
# ---------------------------------------------------------------------------


def test_file_exceeding_quota_is_not_published() -> None:
    """T9: files over quota must be rejected before storage."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "enforce_quota"), "policy.enforce_quota is missing"
    with pytest.raises(Exception):
        module.enforce_quota(
            principal="owner-a",
            current_bytes=5 * 1024 * 1024 * 1024,
            incoming_bytes=2,
            quota_bytes=5 * 1024 * 1024 * 1024,
        )


def test_file_older_than_retention_is_not_retrievable() -> None:
    """T9: files older than retention must not be retrievable."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "is_retrievable"), "policy.is_retrievable is missing"
    import datetime as _dt
    now = _dt.datetime(2026, 9, 3, tzinfo=_dt.timezone.utc)
    age = _dt.timedelta(days=91)
    assert (
        module.is_retrievable(mtime=now - age, now=now, retention_days=90) is False
    ), "files older than retention must not be retrievable"


# ---------------------------------------------------------------------------
# T10 — GDPR erasure regression
# ---------------------------------------------------------------------------


def test_erasure_removes_owner_area_quarantine_and_temp(tmp_path) -> None:
    """T10: erasure must remove all references to the principal."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "erase_principal"), "policy.erase_principal is missing"
    module.erase_principal(principal="owner-a", store_root=tmp_path)
    for sub in ("entries", "quarantine", "tmp"):
        candidate = tmp_path / "owner-a" / sub
        assert not candidate.exists(), f"erasure must remove {sub}"
    assert not (tmp_path / "owner-a").exists(), "owner directory must be gone"


def test_erasure_emits_redacted_audit_event() -> None:
    """T10: erasure must emit a redacted audit event (no raw names)."""
    module = importlib.import_module("cloudbrowser.cloudfiles.audit")
    assert hasattr(module, "record_erasure"), "audit.record_erasure is missing"
    event = module.record_erasure(principal_hash="<h>", request_id="req-1")
    blob = str(event)
    for forbidden in ("@", "/data", ".pdf", "name"):
        assert forbidden not in blob, (
            f"audit event must be redacted (no {forbidden!r})"
        )


# ---------------------------------------------------------------------------
# T11 — Replay via stale binding headers
# ---------------------------------------------------------------------------


def test_gateway_strips_xcb_headers_from_public_request() -> None:
    """T11: gateway must strip X-CB-* headers from the public request."""
    module = importlib.import_module("cloudbrowser.cloudfiles.gateway")
    assert hasattr(module, "sanitize_public_headers"), (
        "gateway.sanitize_public_headers is missing"
    )
    headers = {
        "X-CB-Principal": "owner-b",
        "X-CB-Profile": "p",
        "X-CB-Browser": "b",
        "X-CB-Generation": "1",
    }
    cleaned = module.sanitize_public_headers(headers)
    assert not any(k.lower().startswith("x-cb-") for k in cleaned), (
        "gateway must strip all X-CB-* headers from public requests"
    )


def test_gateway_sets_xcb_headers_from_server_binding() -> None:
    """T11: gateway must set X-CB-* headers from server-derived binding."""
    module = importlib.import_module("cloudbrowser.cloudfiles.gateway")
    assert hasattr(module, "build_internal_headers"), (
        "gateway.build_internal_headers is missing"
    )
    headers = module.build_internal_headers(
        binding={"principal_id": "owner-a", "profile_id": "p",
                 "browser_id": "b", "generation": "1"},
        request_id="req-1",
    )
    for key in ("X-CB-Principal", "X-CB-Profile", "X-CB-Browser",
                "X-CB-Generation", "X-CB-Request-Id"):
        assert key in headers, f"internal headers must include {key}"


# ---------------------------------------------------------------------------
# T12 — Excessive payload
# ---------------------------------------------------------------------------


def test_stream_larger_than_maximum_is_rejected_before_storage() -> None:
    """T12: streams larger than the limit must be rejected before storage."""
    module = importlib.import_module("cloudbrowser.cloudfiles.ingest")
    assert hasattr(module, "bounded_copy"), "ingest.bounded_copy is missing"
    from io import BytesIO
    src = BytesIO(b"x" * 2048)
    with pytest.raises(Exception):
        list(module.bounded_copy(src=src, max_bytes=1024))


def test_response_is_bounded_to_configured_maximum() -> None:
    """T12: gateway must refuse responses larger than the configured max."""
    module = importlib.import_module("cloudbrowser.cloudfiles.gateway")
    assert hasattr(module, "within_size_budget"), (
        "gateway.within_size_budget is missing"
    )
    assert module.within_size_budget(1, max_bytes=2) is True
    assert module.within_size_budget(3, max_bytes=2) is False


# ---------------------------------------------------------------------------
# T13 — Symlink and special-file escape
# ---------------------------------------------------------------------------


def test_storage_does_not_follow_symlinks(tmp_path) -> None:
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


def test_listing_excludes_special_files(tmp_path) -> None:
    """T13: listing must skip anything that is not a regular file."""
    module = importlib.import_module("cloudbrowser.cloudfiles.store")
    assert hasattr(module, "list_entries"), "list_entries is missing"
    special = tmp_path / "owner-a" / "entries" / "weird.sock"
    special.parent.mkdir(parents=True, exist_ok=True)
    special.write_text("")
    listing = module.list_entries(principal="owner-a", store_root=tmp_path)
    assert "weird.sock" not in listing, "special files must not be listed"


# ---------------------------------------------------------------------------
# T14 — Log and audit leakage
# ---------------------------------------------------------------------------


def test_gateway_logs_omit_raw_names_and_principals() -> None:
    """T14: gateway logs must be redacted."""
    module = importlib.import_module("cloudbrowser.cloudfiles.audit")
    assert hasattr(module, "redact_event"), "audit.redact_event is missing"
    event = {
        "name": "invoice.pdf",
        "principal": "owner-a@example.test",
        "size": 10,
    }
    blob = str(module.redact_event(event))
    for forbidden in ("invoice.pdf", "owner-a@example.test"):
        assert forbidden not in blob, f"log must not contain {forbidden!r}"


def test_downloads_logs_omit_raw_names_and_principals() -> None:
    """T14: downloads logs must be redacted."""
    module = importlib.import_module("cloudbrowser.cloudfiles.audit")
    assert hasattr(module, "redact_event"), "audit.redact_event is missing"
    event = {
        "name": "secret.pdf",
        "principal": "owner-b@example.test",
        "size": 5,
    }
    blob = str(module.redact_event(event))
    for forbidden in ("secret.pdf", "owner-b@example.test"):
        assert forbidden not in blob, f"downloads log must not contain {forbidden!r}"


# ---------------------------------------------------------------------------
# T15 — Direct public download URL reuse
# ---------------------------------------------------------------------------


def test_no_presigned_url_route_exists() -> None:
    """T15: there must be no public presigned URL route."""
    module = importlib.import_module("cloudbrowser.cloudfiles.routes")
    assert hasattr(module, "PUBLIC_ROUTES"), "PUBLIC_ROUTES is missing"
    pattern = re.compile(r"/signed/|/token/|/dl/[A-Za-z0-9_-]{16,}")
    for route in module.PUBLIC_ROUTES:
        assert not pattern.search(route), (
            f"public routes must not include presigned URL patterns: {route!r}"
        )


def test_request_without_tinyauth_session_is_unauthorized() -> None:
    """T15: requests without TinyAuth must be unauthorized."""
    module = importlib.import_module("cloudbrowser.cloudfiles.policy")
    assert hasattr(module, "authorize_public_request"), (
        "policy.authorize_public_request is missing"
    )
    with pytest.raises(Exception):
        module.authorize_public_request({"session": None})
