"""Runtime service inventory and agent-control image contract tests."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_agent_control_has_an_independent_entrypoint_and_image() -> None:
    entrypoint = ROOT / "services" / "agent-control" / "entrypoint.py"
    dockerfile = ROOT / "services" / "agent-control" / "Dockerfile"
    assert entrypoint.is_file()
    assert dockerfile.is_file()
    text = dockerfile.read_text(encoding="utf-8")
    for marker in (
        "COPY src/ /app/src/",
        "COPY services/agent-control/entrypoint.py",
        "USER cloudbrowser",
        "HEALTHCHECK",
        "ENTRYPOINT",
    ):
        assert marker in text


def test_agent_control_is_in_each_compose_variant() -> None:
    for filename in ("compose.yaml", "compose.coolify.yaml"):
        text = (ROOT / "deploy" / "coolify" / filename).read_text(encoding="utf-8")
        assert "  agent-control:" in text
        block = text.split("  agent-control:", 1)[1].split("  viewer:", 1)[0]
        assert "agent-control" in block
        assert "CB_BROWSER_API_URL: http://browser:9230" in block
        assert "CB_AGENT_CONTROL_SHARED_SECRET" in block
        assert 'expose:\n      - "8090"' in block
