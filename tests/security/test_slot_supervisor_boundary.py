from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_lifecycle_and_supervisor_do_not_import_legacy_runtime():
    for path in (
        ROOT / "src" / "cloudbrowser" / "browser_slots" / "lifecycle.py",
        ROOT / "src" / "cloudbrowser" / "browser_slots" / "supervisor.py",
        ROOT / "src" / "cloudbrowser" / "browser_slots" / "transport.py",
    ):
        text = path.read_text(encoding="utf-8")
        assert "legacy" not in text
        assert "vault_client" not in text
        assert "subprocess" not in text


def test_transport_contract_does_not_expose_raw_cdp_operations():
    text = (ROOT / "src" / "cloudbrowser" / "browser_slots" / "transport.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("execute", "evaluate", "websocket", "raw_cdp", "getAllCookies"):
        assert forbidden not in text
