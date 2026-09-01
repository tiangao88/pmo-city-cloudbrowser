from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_legacy_restart_api_has_owner_bound_snapshot_primitives():
    source = (ROOT / "legacy" / "scripts" / "restart-api.py").read_text(encoding="utf-8")
    for marker in (
        "LAST_GOOD_SNAPSHOT_FILE",
        "def chrome_owns_profile",
        "def _write_snapshot_file",
        "def load_snapshot",
        "def _read_snapshot",
    ):
        assert marker in source


def test_runtime_extraction_is_explicitly_not_a_direct_vault_import():
    source = (ROOT / "legacy" / "scripts" / "restart-api.py").read_text(encoding="utf-8")
    assert "vault_client" not in source
    assert "LAST_GOOD_SNAPSHOT_FILE" in source
