from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_compose_declares_a_valid_source_build_context_for_each_service():
    compose = (ROOT / "deploy" / "coolify" / "compose.yaml").read_text(encoding="utf-8")
    for service in ("router", "slot-supervisor", "browser", "viewer", "downloads", "credential-broker"):
        assert f"dockerfile: services/{service}/Dockerfile" in compose
        assert (ROOT / "services" / service / "Dockerfile").is_file()


def test_compose_does_not_publish_service_ports_by_default():
    compose = (ROOT / "deploy" / "coolify" / "compose.yaml").read_text(encoding="utf-8")
    assert "ports:" not in compose
