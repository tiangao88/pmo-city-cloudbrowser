from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_v02_baseline_is_immutable_and_not_installable():
    approval = (ROOT / "specs" / "baselines" / "v0.2.0" / "APPROVAL.md").read_text()
    manifest = (ROOT / "deploy" / "coolify" / "releases" / "v0.1.0" / "release-manifest.yaml").read_text()
    assert "approved for test-first implementation" in approval
    assert "live deployment" in approval
    assert "installable: false" in manifest


def test_v02_baseline_covers_required_security_surfaces():
    baseline = (ROOT / "specs" / "baselines" / "v0.2.0" / "README.md").read_text()
    for term in (
        "status only",
        "exact-origin",
        "fail\nclosed",
        "application-level identity verification",
    ):
        assert term in baseline
