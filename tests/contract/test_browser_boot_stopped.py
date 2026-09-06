"""Boot-stopped contract for the browser service (CB_BROWSER_AUTOSTART=0).

Session activation requires the browser container to boot with Chrome NOT
running so the slot supervisor can adopt a server-minted binding (adoption
is stopped-only). The default remains eager auto-start.
"""

from __future__ import annotations

import threading


class _FakeRegistry:
    def __init__(self) -> None:
        self.closed = False

    def attach_stop_event(self, stop_event) -> None:
        pass

    def on_binding(self, binding) -> None:
        pass

    def close(self) -> None:
        self.closed = True

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


def test_browser_service_boot_stopped_skips_eager_start(monkeypatch) -> None:
    process, server, stop_event = FakeProcess(), FakeServer(), threading.Event()
    monkeypatch.setattr(browser_service, "build_browser_service", lambda: (process, server, stop_event, _FakeRegistry()))
    monkeypatch.setattr(browser_service, "build_download_watcher", lambda: None)
    monkeypatch.setenv("CB_BROWSER_AUTOSTART", "0")
    browser_service.run_browser_service()
    assert process.started is False
    assert server.served is True
    assert process.stopped is True
    assert server.closed is True


def test_browser_service_default_remains_autostart(monkeypatch) -> None:
    process, server, stop_event = FakeProcess(), FakeServer(), threading.Event()
    monkeypatch.setattr(browser_service, "build_browser_service", lambda: (process, server, stop_event, _FakeRegistry()))
    monkeypatch.setattr(browser_service, "build_download_watcher", lambda: None)
    monkeypatch.delenv("CB_BROWSER_AUTOSTART", raising=False)
    browser_service.run_browser_service()
    assert process.started is True
