"""Installation contract for the non-root browser image."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_browser_image_prepares_both_named_volume_mountpoints() -> None:
    text = (ROOT / "services" / "browser" / "Dockerfile").read_text(encoding="utf-8")
    preparation = "mkdir -p /data/profile /data/downloads-browser"
    assert preparation in text
    assert "chown -R cloudbrowser:cloudbrowser /app /data" in text
    assert text.index(preparation) < text.index("USER cloudbrowser")
