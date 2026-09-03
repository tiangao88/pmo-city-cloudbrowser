"""Contract tests for the public downloads host configuration."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_public_files_host_is_the_authorized_cloudfiles2_domain() -> None:
    env = (ROOT / "deploy" / "coolify" / ".env.example").read_text(encoding="utf-8")
    assert "CB_PUBLIC_FILES_HOST=cloudfiles2.dev01.pmo.city" in env
    assert "CB_PUBLIC_FILES_HOST=files.example.invalid" not in env


def test_downloads_service_is_exposed_without_host_port_publishing() -> None:
    for name in ("compose.yaml", "compose.coolify.yaml"):
        text = (ROOT / "deploy" / "coolify" / name).read_text(encoding="utf-8")
        start = text.index("  downloads:\n")
        end = text.find("\n  credential-broker:", start)
        block = text[start:end]
        assert "expose:\n      - \"8083\"" in block
        assert "ports:" not in block
