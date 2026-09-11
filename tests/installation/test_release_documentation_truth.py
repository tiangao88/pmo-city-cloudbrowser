from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_root_readme_matches_qualified_release_and_disabled_form_mode() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split()).lower()

    for stale_claim in (
        "controlled ordinary form adapter",
        "pre-build and not installable",
    ):
        assert stale_claim not in normalized
    assert "production form mode is disabled" in normalized
    assert "image-qualified and installable" in normalized


def test_coolify_guide_uses_current_cloudfiles_and_digest_pinned_contract() -> None:
    guide = (ROOT / "deploy/coolify/README.md").read_text(encoding="utf-8")

    for stale_claim in (
        "internal `downloads` service; the planned public `cloudfiles` gateway is not",
        "pins the published dev\nimages (`ghcr.io/tiangao88/pmo-city-cloudbrowser/<service>:v0.2.0-dev1`)",
        "The downloads service is fronted at `cloudfiles2.dev01.pmo.city`",
        "cloudbrowser2-downloads",
        "pre-build and not installable",
    ):
        assert stale_claim not in guide
    assert "cloudbrowser2-cloudfiles" in guide
    assert "immutable image digests" in guide
    assert "release manifest is installable" in guide
    assert "--env-file deploy/coolify/.env" in guide


def test_source_compose_env_example_assigns_every_required_input() -> None:
    import re

    compose = (ROOT / "deploy/coolify/compose.yaml").read_text(encoding="utf-8")
    example = (ROOT / "deploy/coolify/.env.example").read_text(encoding="utf-8")
    required = set(re.findall(r"\$\{([A-Z0-9_]+):\?", compose))
    assigned = {
        line.split("=", 1)[0]
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert required <= assigned


def test_qualification_index_names_the_current_source_and_run() -> None:
    index = (ROOT / "deploy/coolify/image-qualification/README.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(index.split())

    assert "remain `status: pending`" not in normalized
    assert "qualification run `34603628801`" in normalized
    assert "commit `8e455b4efbbde723c26c47879da1b339ca3835b5`" in normalized
    assert "synchronized all digests and provenance atomically" in normalized
