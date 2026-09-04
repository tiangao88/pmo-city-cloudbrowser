"""Readiness tests for the internal downloads dependency."""

from __future__ import annotations

from cloudbrowser.cloudfiles.downloads_client import DownloadsClient


def test_ready_rejects_a_healthy_but_oversized_response(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b"x" * 11

    monkeypatch.setattr(
        "cloudbrowser.cloudfiles.downloads_client.urlopen",
        lambda *args, **kwargs: Response(),
    )
    client = DownloadsClient("http://downloads:8083", "s" * 32, max_response_bytes=10)
    assert client.ready is False
