"""Installation tests for the downloads service."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_downloads_dockerfile_uses_supported_base_and_marks_data_volume() -> None:
    text = (ROOT / "services" / "downloads" / "Dockerfile").read_text(encoding="utf-8")
    assert text.startswith("FROM python:3.12-slim\n")
    assert "/data/downloads" in text
    assert "USER cloudbrowser" in text
    assert "HEALTHCHECK" in text
    assert "COPY services/downloads/entrypoint.py" in text


def test_downloads_entrypoint_invokes_service_runtime() -> None:
    text = (ROOT / "services" / "downloads" / "entrypoint.py").read_text(encoding="utf-8")
    assert "run_service(\"downloads\")" in text


def test_compose_files_require_owner_binding_and_shared_secret() -> None:
    import re

    # The source-build variant requires every value; the Coolify variant
    # self-provisions via magic envs (secrets) and deploy-safe defaults.
    variant_markers = {
        "compose.yaml": (
            "CB_INSTANCE_ID:?CB_INSTANCE_ID is required",
            "CB_RELEASE_VERSION:?CB_RELEASE_VERSION is required",
            "CB_PRINCIPAL_ID:?CB_PRINCIPAL_ID is required",
            "CB_BROWSER_ID:?CB_BROWSER_ID is required",
            "CB_BINDING_GENERATION:?CB_BINDING_GENERATION is required",
            "CB_DOWNLOADS_SHARED_SECRET:?CB_DOWNLOADS_SHARED_SECRET is required",
        ),
        "compose.coolify.yaml": (
            "CB_INSTANCE_ID: ${CB_INSTANCE_ID:-cloudbrowser2-dev-v01}",
            "CB_RELEASE_VERSION: ${CB_RELEASE_VERSION:-0.2.0-dev1}",
            "CB_PRINCIPAL_ID: ${CB_PRINCIPAL_ID:-principal-dev01}",
            "CB_BROWSER_ID: ${CB_BROWSER_ID:-browser-dev01}",
            "CB_BINDING_GENERATION: ${CB_BINDING_GENERATION:-generation-dev01-g1}",
            "CB_DOWNLOADS_SHARED_SECRET: ${SERVICE_PASSWORD_64_DLSECRET}",
        ),
    }
    for name, markers in variant_markers.items():
        text = (ROOT / "deploy" / "coolify" / name).read_text(encoding="utf-8")
        match = re.search(r"^  downloads:\n(?P<body>(?:^    .*\n?)+)", text, re.MULTILINE)
        assert match is not None, f"{name}: missing downloads service block"
        body = match.group("body")
        for marker in markers:
            assert marker in body, f"{name}: missing {marker}"
