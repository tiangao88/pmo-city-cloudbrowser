"""Runtime wiring contracts for the production browser-download transport.

The browser service must start the download watcher only when the full server
configuration is present (download directory + ingest receiver URL + shared
secret), derive the owner binding from its own server environment, and shut
the watcher down cleanly with the rest of the service.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import cloudbrowser.browser_service as browser_service


class FakeProcess:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.watched = False

    def start(self, **kwargs) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def watch(self, stop_event: object, **kwargs) -> None:
        self.watched = True


class FakeServer:
    def __init__(self) -> None:
        self.served = False
        self.closed = False

    def serve_forever(self) -> None:
        self.served = True

    def server_close(self) -> None:
        self.closed = True


def _install_fakes(monkeypatch):
    process, server, stop_event = FakeProcess(), FakeServer(), threading.Event()
    monkeypatch.setattr(browser_service, "build_browser_service", lambda: (process, server, stop_event))
    return process, server, stop_event


def _clear_watcher_env(monkeypatch) -> None:
    for name in (
        "CB_BROWSER_DOWNLOAD_DIR",
        "CB_DOWNLOADS_INGEST_URL",
        "CB_DOWNLOADS_INGEST_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_download_watcher_requires_full_server_configuration(monkeypatch, tmp_path: Path) -> None:
    _clear_watcher_env(monkeypatch)
    assert browser_service.build_download_watcher() is None

    monkeypatch.setenv("CB_BROWSER_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    assert browser_service.build_download_watcher() is None

    monkeypatch.setenv("CB_DOWNLOADS_INGEST_URL", "http://ingest:8086")
    assert browser_service.build_download_watcher() is None


def test_build_download_watcher_uses_server_binding_and_configured_dir(monkeypatch, tmp_path: Path) -> None:
    _clear_watcher_env(monkeypatch)
    monkeypatch.setenv("CB_BROWSER_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("CB_DOWNLOADS_INGEST_URL", "http://ingest:8086")
    monkeypatch.setenv("CB_DOWNLOADS_INGEST_SECRET", "runtime-secret-0123456789abcdef")
    monkeypatch.setenv("CB_PRINCIPAL_ID", "owner@example.test")
    monkeypatch.setenv("CB_PROFILE_ID", "profile-runtime")
    monkeypatch.setenv("CB_BROWSER_ID", "browser-runtime")
    monkeypatch.setenv("CB_BINDING_GENERATION", "generation-runtime")

    watcher = browser_service.build_download_watcher()

    assert watcher is not None
    watcher.emit_once()
    assert (tmp_path / "downloads").is_dir()
    watcher.close()


def test_build_download_watcher_rejects_invalid_limit(monkeypatch, tmp_path: Path) -> None:
    _clear_watcher_env(monkeypatch)
    monkeypatch.setenv("CB_BROWSER_DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("CB_DOWNLOADS_INGEST_URL", "http://ingest:8086")
    monkeypatch.setenv("CB_DOWNLOADS_INGEST_SECRET", "runtime-secret-0123456789abcdef")
    monkeypatch.setenv("CB_BROWSER_DOWNLOAD_MAX_BYTES", "not-an-int")

    with pytest.raises(SystemExit, match="integer"):
        browser_service.build_download_watcher()


def test_browser_service_starts_and_stops_watcher_when_configured(monkeypatch, tmp_path: Path) -> None:
    process, server, _ = _install_fakes(monkeypatch)
    captured: dict[str, object] = {}

    def fake_build():
        from cloudbrowser.cloudfiles.browser_downloads import (
            BrowserDownloadWatcher,
            DownloadWatchConfig,
        )
        from cloudbrowser.cloudfiles.contracts import PrincipalBinding

        def submit(event):
            raise AssertionError("no downloads in this runtime test")

        watcher = BrowserDownloadWatcher(
            DownloadWatchConfig(
                download_dir=tmp_path / "downloads",
                binding=PrincipalBinding(principal_id="owner@example.test"),
            ),
            submit=submit,
        )
        captured["watcher"] = watcher
        return watcher

    monkeypatch.setattr(browser_service, "build_download_watcher", fake_build)
    browser_service.run_browser_service()

    assert process.started is True
    assert server.served is True
    assert process.stopped is True
    assert server.closed is True
    watcher = captured["watcher"]
    with pytest.raises(RuntimeError, match="closed"):
        watcher.emit_once()
