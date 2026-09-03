# CloudFiles Phase 0 boundary red tests

> Version: **v0.2 development proposal — 2026-09-03**
> Status: **PROPOSED — Phase 0 entry**

These tests define the security and contract boundaries for CloudFiles. They
must be written first and observed failing for the intended reasons before
any Phase 1 production implementation. After Phase 0 closes, they remain as the
boundary invariant suite that subsequent phases extend.

## Convention

- Tests live under `tests/contract/test_cloudfiles_v1_gateway_boundary.py`,
  `tests/security/test_cloudfiles_v1_gateway_security.py`, and
  `tests/security/test_cloudfiles_gateway_exposure.py` (public-host exposure
  and unsafe-header forwarding, threats X1/X2 in the threat model).
- Each test references the threat and matrix IDs in
  `specs/proposals/v0.2/92-cloudfiles-route-response-matrix.md` and
  `specs/proposals/v0.2/94-cloudfiles-threat-model.md`.
- Tests use injectable ports (storage, scanner, clock, identity) and must not
  depend on TinyAuth, the network, or any deployed service.
- Each test must fail with a specific reason and not by import error or
  collection failure.

## Threat to test mapping

### T1 — Forged public identity (matrix §trust)

- `test_remote_email_header_is_not_authoritative`: a request carrying
  `Remote-Email: victim@…` must not influence the principal; result is
  `owner_binding_unavailable` or `unauthorized`.
- `test_xcb_principal_header_is_not_authoritative`: a request carrying
  `X-CB-Principal: <other>` must not affect the principal.
- `test_query_string_owner_is_not_authoritative`: `?owner=<other>` must not
  select another principal.

### T2 — Cross-principal read

- `test_listing_for_principal_a_excludes_principal_b_files`.
- `test_reading_a_file_under_principal_b_from_principal_a_request_is_rejected`.
- `test_storage_paths_are_rooted_under_server_bound_principal`: store must
  refuse writes/reads whose resolved path escapes the owner area.

### T3 — Stale, revoked, or missing binding

- `test_no_tinyauth_session_returns_unauthorized`.
- `test_missing_binding_returns_owner_binding_unavailable`.
- `test_revoked_binding_returns_owner_binding_unavailable`.
- `test_stale_binding_returns_owner_binding_unavailable`.

### T4 — Path traversal and unsafe filenames

- `test_dotdot_in_name_is_rejected`.
- `test_slash_in_name_is_rejected`.
- `test_backslash_in_name_is_rejected`.
- `test_hidden_name_is_rejected`.
- `test_null_byte_in_name_is_rejected`.
- `test_percent_decoded_escape_is_rejected`.

### T5 — Header injection

- `test_filename_with_crlf_is_rejected_before_header_written`.
- `test_filename_with_quote_is_handled_safely`.

### T6 — Direct downloads exposure

- `test_compose_must_not_route_public_host_to_downloads_container`: parse
  `deploy/coolify/compose.yaml` and `compose.coolify.yaml`; assert that no
  public `cloudfiles*` host resolves to the `downloads` container.
- `test_downloads_container_binds_only_to_internal_interface`.

### T7 — Identity leak in error/listing

- `test_health_response_omits_identity`.
- `test_listing_response_omits_principal_id_and_paths`.
- `test_error_envelope_uses_bounded_error_code_and_request_id`.
- `test_internal_headers_are_not_echoed_in_public_response`.

### T8 — Quarantine retrieval

- `test_quarantined_files_are_not_listed`.
- `test_direct_read_of_quarantined_name_returns_not_found`.

### T9 — Quota/retention tampering

- `test_file_exceeding_quota_is_not_published`.
- `test_file_older_than_retention_is_not_retrievable`.

### T10 — GDPR erasure regression

- `test_erasure_removes_owner_area_quarantine_and_temp`.
- `test_erasure_emits_redacted_audit_event`.

### T11 — Replay via stale binding headers

- `test_gateway_strips_xcb_headers_from_public_request`.
- `test_gateway_sets_xcb_headers_from_server_binding`.

### T12 — Excessive payload

- `test_stream_larger_than_maximum_is_rejected_before_storage`.
- `test_response_is_bounded_to_configured_maximum`.

### T13 — Symlink and special-file escape

- `test_storage_does_not_follow_symlinks`.
- `test_listing_excludes_special_files`.

### T14 — Log and audit leakage

- `test_gateway_logs_omit_raw_names_and_principals`.
- `test_downloads_logs_omit_raw_names_and_principals`.

### T15 — Direct public download URL reuse

- `test_no_presigned_url_route_exists`.
- `test_request_without_tinyauth_session_is_unauthorized`.

## Acceptance gate

Phase 0 is complete when:

- every test listed above is implemented;
- each test has been observed failing with the intended reason;
- the documentation matrix and threat model are referenced from each test
  docstring;
- no production code under `src/cloudbrowser/cloudfiles` or
  `services/cloudfiles` exists yet;
- the `Makefile` includes a new target `cloudfiles-boundary` that runs both
  test files;
- the test suite is green when the production implementation is later added
  in Phases 1–3.
