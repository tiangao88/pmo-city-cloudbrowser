"""Auto-start contract for the browser service boot path."""

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
        from types import SimpleNamespace
        self.config = SimpleNamespace(owner="owner-test", profile_id="profile-test", browser_id="browser-test", generation="g1")
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


def test_browser_service_autostarts_chrome_before_serving(monkeypatch) -> None:
    process, server, stop_event = FakeProcess(), FakeServer(), threading.Event()
    monkeypatch.setattr(browser_service, "build_browser_service", lambda: (process, server, stop_event, _FakeRegistry()))
    browser_service.run_browser_service()
    assert process.started is True
    assert server.served is True
    assert process.stopped is True
    assert server.closed is True
