from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_contract_surfaces_are_versioned():
    expected = {
        "control-api/v1/README.md",
        "agent-control/v1/README.md",
        "credential-broker/v1/README.md",
        "events/v1/README.md",
    }
    actual = {
        str(path.relative_to(ROOT / "specs" / "contracts"))
        for path in (ROOT / "specs" / "contracts").rglob("README.md")
    }
    assert expected <= actual


def test_coolify_bundle_requires_instance_isolation():
    text = (ROOT / "deploy" / "coolify" / "README.md").read_text(encoding="utf-8")
    for term in ("CB_INSTANCE_ID", "network", "volumes", "secret namespaces"):
        assert term in text
