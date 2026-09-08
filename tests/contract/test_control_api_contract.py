from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_control_api_contract_is_no_longer_a_placeholder():
    readme = (ROOT / "specs" / "contracts" / "control-api" / "v1" / "README.md").read_text(
        encoding="utf-8"
    )
    openapi = (ROOT / "specs" / "contracts" / "control-api" / "v1" / "openapi.yaml").read_text(
        encoding="utf-8"
    )
    assert "Placeholder" not in readme
    for operation in ("wake", "suspend", "stop", "recreate"):
        assert operation in readme
        assert operation in openapi
    assert "/control:" in openapi
    assert "raw CDP" in readme


def test_openapi_covers_the_implemented_router_surface():
    """Every shipped router route must appear in the v1 OpenAPI document."""
    openapi = (ROOT / "specs" / "contracts" / "control-api" / "v1" / "openapi.yaml").read_text(
        encoding="utf-8"
    )
    for route in (
        "/v1/session:",
        "/v1/session/activate:",
        "/v1/session/leave:",
        "/v1/roster:",
        "/v1/agent/{operation}:",
    ):
        assert route in openapi, f"missing OpenAPI path {route}"
    for operation in ("navigate", "click", "type", "page_info", "tabs_list"):
        assert operation in openapi, f"missing allowlisted agent operation {operation}"
    # Bounded-envelope response fields that callers depend on.
    for field in ("session_ttl_s", "offer_ttl_s", "error_code", "entries"):
        assert field in openapi, f"missing response field {field}"


def test_cloudfiles_phase_statuses_are_refreshed():
    """Spec 91 statuses must reflect shipped phases, not the pre-Phase-0 map."""
    spec91 = (
        ROOT / "specs" / "proposals" / "v0.2" / "91-cloudfiles-delivery-phases.md"
    ).read_text(encoding="utf-8")
    assert "Phase 0\npending" not in spec91
    assert "planning map — 2026-09-03" not in spec91
    for phase in ("Phase 0", "Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5"):
        assert phase in spec91
    assert "**Current status:** delivered" in spec91
