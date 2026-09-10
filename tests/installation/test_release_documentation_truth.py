from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_root_readme_matches_prebuild_release_and_disabled_form_mode() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split()).lower()

    for stale_claim in (
        "controlled ordinary form adapter",
        "digest-pinned, installable manifest",
        "release is now digest-pinned and installable",
    ):
        assert stale_claim not in normalized
    assert "production form mode is disabled" in normalized
    assert "pre-build and not installable" in normalized


def test_coolify_guide_uses_current_cloudfiles_and_digest_pinned_contract() -> None:
    guide = (ROOT / "deploy/coolify/README.md").read_text(encoding="utf-8")

    for stale_claim in (
        "internal `downloads` service; the planned public `cloudfiles` gateway is not",
        "pins the published dev\nimages (`ghcr.io/tiangao88/pmo-city-cloudbrowser/<service>:v0.2.0-dev1`)",
        "The downloads service is fronted at `cloudfiles2.dev01.pmo.city`",
        "cloudbrowser2-downloads",
        "`installable: true`",
    ):
        assert stale_claim not in guide
    assert "cloudbrowser2-cloudfiles" in guide
    assert "immutable image digests" in guide
    assert "pre-build and not installable" in guide
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


def test_qualification_index_marks_all_retained_records_stale_for_current_source() -> None:
    index = (ROOT / "deploy/coolify/image-qualification/README.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(index.split())

    assert "remain `status: pending`" not in normalized
    assert "prior qualification run `34402569940`" in normalized
    assert "commit `50ce1984448ddf79621d4114f81c6a2b2b83d5fa`" in normalized
    assert "do not qualify the current source" in normalized
