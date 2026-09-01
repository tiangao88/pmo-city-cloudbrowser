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
