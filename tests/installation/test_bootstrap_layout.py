from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_keeps_legacy_material_explicitly_separate():
    required = [
        ROOT / "legacy" / "README.md",
        ROOT / "legacy" / "scripts" / "router.py",
        ROOT / "specs" / "archive" / "pmo-city-builds-w2-w3" / "README.md",
        ROOT / "specs" / "proposals" / "v0.2" / "85-credential-broker-prd.md",
        ROOT / "specs" / "proposals" / "v0.2" / "86-product-boundaries.md",
        ROOT / "specs" / "proposals" / "v0.2" / "87-broker-security-model.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    assert not missing, f"missing bootstrap paths: {missing}"


def test_bootstrap_has_non_installable_release_marker():
    manifest = (
        ROOT / "deploy" / "coolify" / "releases" / "v0.1.0" / "release-manifest.yaml"
    ).read_text(encoding="utf-8")
    assert "installable: false" in manifest
    assert "historical-import-only" in manifest
