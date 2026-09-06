"""RED: deployment wiring for the browser-download ingest transport.

Decision 2026-09-06 (Tigo): wire the transport for real (option 1) with a
per-slot binding injected by the slot-supervisor path (option 1).

This file pins the deployment-wiring half:

- ``create_cloudfiles_runtime`` binds ``create_ingest_server`` on an
  internal port (default 8086) when ``ingest_secret`` is configured, and
  the cloudfiles entrypoint reads it from ``CB_DOWNLOADS_INGEST_SECRET``;
- the browser service gets the watcher envs, a Chrome download directory
  under a dedicated volume, and requires real (non-unassigned) binding
  identity when the watcher is configured;
- both compose variants declare the ``CB_DOWNLOADS_INGEST_SECRET``, share
  the durable downloads volume with cloudfiles, and point Chrome at the
  watched download directory.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from cloudbrowser.cloudfiles.ingest_client import IngestClient
from cloudbrowser.cloudfiles.runtime import create_cloudfiles_runtime

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy" / "coolify"

_INGEST_SECRET = "ingest-receiver-secret-0123456789"


# ---------------------------------------------------------------------------
# cloudfiles runtime binds the ingest receiver
# ---------------------------------------------------------------------------


def _runtime_kwargs(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        downloads_base_url="http://downloads:8083",
        shared_secret="runtime-shared-secret-0123456789",
        instance_id="cloudbrowser2-dev-v01",
        release_version="0.2.0-dev1",
        store_root=tmp_path / "store",
        notifier=lambda event: None,
    )
    kwargs.update(extra)
    return kwargs


def test_create_runtime_wires_ingest_receiver_when_secret_configured(tmp_path):
    runtime = create_cloudfiles_runtime(
        **_runtime_kwargs(tmp_path, ingest_secret=_INGEST_SECRET, ingest_port=0)
    )
    try:
        server = runtime.ingest_server
        assert server is not None
        port = server.server_address[1]
        assert port > 0
        # The receiver must actually answer the health route.
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/health", timeout=3
        ) as response:
            assert response.status == 200
    finally:
        runtime.close()


def test_runtime_without_ingest_secret_keeps_receiver_inert(tmp_path):
    runtime = create_cloudfiles_runtime(**_runtime_kwargs(tmp_path))
    try:
        assert runtime.ingest_server is None
    finally:
        runtime.close()


def test_runtime_close_shuts_down_ingest_server(tmp_path):
    runtime = create_cloudfiles_runtime(
        **_runtime_kwargs(tmp_path, ingest_secret=_INGEST_SECRET, ingest_port=0)
    )
    server = runtime.ingest_server
    assert server is not None
    port = server.server_address[1]
    runtime.close()
    assert runtime.ingest_server is None
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
    # close() is idempotent
    runtime.close()


def test_runtime_rejects_invalid_ingest_port(tmp_path):
    with pytest.raises(ValueError):
        create_cloudfiles_runtime(
            **_runtime_kwargs(tmp_path, ingest_secret=_INGEST_SECRET, ingest_port=-1)
        )


def test_ingest_end_to_end_through_wired_runtime(tmp_path):
    """A real IngestClient POST against the wired receiver publishes a file."""
    from cloudbrowser.cloudfiles.scanner import CleanScanner

    runtime = create_cloudfiles_runtime(
        **_runtime_kwargs(
            tmp_path,
            scanner=CleanScanner(),
            ingest_secret=_INGEST_SECRET,
            ingest_port=0,
        )
    )
    try:
        server = runtime.ingest_server
        assert server is not None
        port = server.server_address[1]
        client = IngestClient(
            base_url=f"http://127.0.0.1:{port}",
            shared_secret=_INGEST_SECRET,
            timeout_s=30.0,
        )
        from cloudbrowser.cloudfiles.contracts import PrincipalBinding

        binding = PrincipalBinding(
            principal_id="pmo-abc123",
            profile_id="profile-pmo-abc123",
            browser_id="slot-A",
            generation="generation-s1",
            request_id="req-e2e0001",
        )
        import io

        receipt = client.submit(
            binding=binding,
            source_name="wired.txt",
            source=io.BytesIO(b"hello wired world"),
            size=17,
        )
        assert receipt.status in ("published", "quarantined")
        entries = runtime.store.list_entries("pmo-abc123")
        assert [entry.name for entry in entries] == ["wired.txt"]
    finally:
        runtime.close()


# ---------------------------------------------------------------------------
# cloudfiles entrypoint env wiring
# ---------------------------------------------------------------------------


def test_entrypoint_reads_ingest_env(monkeypatch):
    source = (ROOT / "src" / "cloudbrowser" / "cloudfiles_entrypoint.py").read_text(
        encoding="utf-8"
    )
    assert "CB_DOWNLOADS_INGEST_SECRET" in source
    assert "CB_DOWNLOADS_INGEST_PORT" in source


# ---------------------------------------------------------------------------
# browser service env wiring
# ---------------------------------------------------------------------------


def _browser_env(monkeypatch, tmp_path: Path, *, unassigned: bool = False) -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "cloudbrowser2-dev-v01")
    monkeypatch.setenv("CB_RELEASE_VERSION", "0.2.0-dev1")
    monkeypatch.setenv("CB_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("CB_BROWSER_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("CB_DOWNLOADS_INGEST_URL", "http://cloudfiles:8086")
    monkeypatch.setenv("CB_DOWNLOADS_INGEST_SECRET", _INGEST_SECRET)
    if unassigned:
        monkeypatch.setenv("CB_PRINCIPAL_ID", "principal-unassigned")
    else:
        monkeypatch.setenv("CB_PRINCIPAL_ID", "pmo-abc123")
        monkeypatch.setenv("CB_PROFILE_ID", "profile-pmo-abc123")
        monkeypatch.setenv("CB_BROWSER_ID", "slot-A")
        monkeypatch.setenv("CB_BINDING_GENERATION", "generation-s1")


def test_browser_watcher_gets_binding_from_server_envs(monkeypatch, tmp_path):
    from cloudbrowser.browser_service import build_download_watcher

    _browser_env(monkeypatch, tmp_path)
    watcher = build_download_watcher()
    assert watcher is not None
    binding = watcher._config.binding
    assert binding.principal_id == "pmo-abc123"
    assert binding.profile_id == "profile-pmo-abc123"
    assert binding.browser_id == "slot-A"
    assert binding.generation == "generation-s1"


def test_browser_watcher_rejects_unassigned_binding(monkeypatch, tmp_path):
    from cloudbrowser.browser_service import build_download_watcher

    _browser_env(monkeypatch, tmp_path, unassigned=True)
    with pytest.raises(SystemExit):
        build_download_watcher()


def test_chrome_command_pins_profile_local_download_directory(monkeypatch, tmp_path):
    """Chrome must download into the watched directory (dedicated volume)."""
    from cloudbrowser.browser_slots.browser_process import BrowserProcessConfig

    _browser_env(monkeypatch, tmp_path)
    download_dir = Path(os.environ["CB_BROWSER_DOWNLOAD_DIR"])
    config = BrowserProcessConfig(
        executable="/usr/bin/chromium",
        profile_dir=Path(os.environ["CB_PROFILE_DIR"]),
        http_port=9222,
        owner=os.environ["CB_PRINCIPAL_ID"],
        generation=os.environ["CB_BINDING_GENERATION"],
        extra_args=(),
        download_dir=download_dir,
    )
    assert "--user-data-dir=" in " ".join(config.command())
    assert f"--download-dir={download_dir}" in config.command()


# ---------------------------------------------------------------------------
# compose wiring (both variants)
# ---------------------------------------------------------------------------


def _block(filename: str, service: str, nxt: str) -> str:
    compose = (COMPOSE_DIR / filename).read_text(encoding="utf-8")
    start = compose.index(f"\n  {service}\n") + 1
    rest = compose[start + len(f"  {service}:") :]
    # stop at the next two-space-indented service key
    import re

    match = re.search(r"\n  [a-z][a-z0-9-]*:", rest)
    if match:
        return rest[: match.start()]
    return rest


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_compose_cloudfiles_declares_ingest_secret_and_port(filename):
    block = _block(filename, "cloudfiles:", "clamav:")
    marker = (
        "CB_DOWNLOADS_INGEST_SECRET: ${SERVICE_PASSWORD_64_INGESTSECRET}"
        if filename == "compose.coolify.yaml"
        else "CB_DOWNLOADS_INGEST_SECRET: ${CB_DOWNLOADS_INGEST_SECRET"
    )
    assert marker in block
    assert "CB_DOWNLOADS_INGEST_PORT: 8086" in block
    assert "expose:" in block and "8086" in block


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_compose_shares_downloads_volume_with_cloudfiles(filename):
    block = _block(filename, "cloudfiles:", "clamav:")
    assert "downloads:/data/downloads:ro" in block


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_compose_browser_wires_watcher_envs(filename):
    block = _block(filename, "browser:", "agent-control:")
    marker = (
        "CB_DOWNLOADS_INGEST_SECRET: ${SERVICE_PASSWORD_64_INGESTSECRET}"
        if filename == "compose.coolify.yaml"
        else "CB_DOWNLOADS_INGEST_SECRET: ${CB_DOWNLOADS_INGEST_SECRET"
    )
    assert "CB_BROWSER_DOWNLOAD_DIR: /data/downloads-browser" in block
    assert "CB_DOWNLOADS_INGEST_URL: http://cloudfiles:8086" in block
    assert marker in block


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.coolify.yaml"])
def test_compose_browser_download_volume_is_dedicated(filename):
    compose = (COMPOSE_DIR / filename).read_text(encoding="utf-8")
    assert "browser-downloads:" in compose
