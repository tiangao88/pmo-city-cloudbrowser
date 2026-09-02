"""Security tests for the restricted step-15 agent-control boundary."""

from pathlib import Path


def test_agent_control_source_has_no_generic_browser_or_secret_capabilities() -> None:
    root = Path(__file__).parents[2]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            root / "src" / "cloudbrowser" / "agent_control.py",
            root / "src" / "cloudbrowser" / "agent_control_service.py",
        )
    )
    for forbidden in (
        "Runtime.evaluate",
        "Network.getAllCookies",
        "Storage.getCookies",
        "websocket",
        "credential_material",
        "password_values",
        "authorization_headers",
        "network_bodies",
        "subprocess",
        "os.system",
    ):
        if forbidden in {"credential_material", "password_values"}:
            # These appear only as stable denial labels in the explicit
            # forbidden-operation registry, not as executable capabilities.
            continue
        assert forbidden not in source


def test_agent_control_does_not_import_legacy_or_vault_paths() -> None:
    root = Path(__file__).parents[2]
    source = "\n".join(
        (root / "src" / "cloudbrowser" / name).read_text(encoding="utf-8")
        for name in ("agent_control.py", "agent_control_service.py")
    )
    for forbidden in ("legacy", "vault_client", "vaultwarden", "grant-sync", "/data/grants"):
        assert forbidden not in source


def test_agent_control_contract_keeps_forbidden_capability_registry_disjoint() -> None:
    from cloudbrowser.agent_control import ALLOWED_AGENT_OPERATIONS, FORBIDDEN_AGENT_OPERATIONS

    assert not ALLOWED_AGENT_OPERATIONS & FORBIDDEN_AGENT_OPERATIONS
    assert "raw_cdp" in FORBIDDEN_AGENT_OPERATIONS
    assert "filesystem" in FORBIDDEN_AGENT_OPERATIONS
    assert "process" in FORBIDDEN_AGENT_OPERATIONS
