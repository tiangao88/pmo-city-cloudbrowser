from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_broker_contract_defines_status_only_response():
    contract = (ROOT / "specs" / "contracts" / "credential-broker" / "v1" / "contract.md").read_text()
    for status in ("authenticated", "mfa_required", "failed", "not_shared", "unsupported"):
        assert f"`{status}`" in contract
    for forbidden in ("passwords", "tokens", "cookies", "network bodies", "raw exception text"):
        assert forbidden in contract


def test_agent_contract_defines_mandatory_denials():
    contract = (ROOT / "specs" / "contracts" / "agent-control" / "v1" / "contract.md").read_text()
    for forbidden in (
        "credential material",
        "cookie values",
        "storage values",
        "network bodies",
        "raw CDP",
        "filesystem",
        "process control",
    ):
        assert forbidden in contract
