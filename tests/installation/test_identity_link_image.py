"""Identity-link service image qualification template tests."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_identity_link_image_inputs_are_present():
    service = ROOT / "services" / "identity-link"
    assert (service / "Dockerfile").is_file()
    assert (service / "entrypoint.py").is_file()
    text = (service / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY src/ /app/src/" in text
    assert "COPY services/identity-link/entrypoint.py" in text
    assert "USER cloudbrowser" in text
    assert "HEALTHCHECK" in text
