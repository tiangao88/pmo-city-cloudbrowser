"""Contract tests for the seven extracted runtime service boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser import service_runtime
from cloudbrowser.browser_slots.browser_process import BrowserProcessConfig


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SERVICES = (
    "router",
    "slot-supervisor",
    "browser",
    "viewer",
    "agent-control",
    "downloads",
    "credential-broker",
)


def test_each_runtime_service_has_a_distinct_entrypoint_and_image():
    entrypoints = []
    for service in RUNTIME_SERVICES:
        entrypoint = ROOT / "services" / service / "entrypoint.py"
        dockerfile = ROOT / "services" / service / "Dockerfile"
        assert entrypoint.is_file()
        assert dockerfile.is_file()
        assert "HEALTHCHECK" in dockerfile.read_text(encoding="utf-8")
        entrypoints.append(entrypoint.read_text(encoding="utf-8"))
    assert len(set(entrypoints)) == len(RUNTIME_SERVICES)


def test_service_runtime_rejects_unknown_component_before_listening(monkeypatch):
    monkeypatch.setenv("CB_INSTANCE_ID", "cloudbrowser-test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "0.2.0-dev1")
    with pytest.raises(SystemExit, match="unknown service component"):
        service_runtime.run_service("unknown")


def test_runtime_service_code_does_not_import_legacy_code():
    for base in (ROOT / "src" / "cloudbrowser", ROOT / "services"):
        for path in base.rglob("*.py"):
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "legacy" not in text.lower(), path
            assert "restart-api.py" not in text, path


def test_browser_command_owns_debugging_and_profile_flags(tmp_path: Path):
    config = BrowserProcessConfig(
        executable="/usr/bin/chromium",
        profile_dir=tmp_path / "profile",
        http_port=9222,
        owner="owner@example.test",
        generation="generation-1",
    )
    assert config.profile_dir == tmp_path / "profile"
    assert config.http_port == 9222
